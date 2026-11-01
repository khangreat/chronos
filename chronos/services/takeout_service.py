"""TakeoutService — ingest the Chronos-owned parts of a Google Takeout and hand
off the rest to the apps that own it.

"Ingest, then route by ownership": Chronos takes browser bookmarks/history and
saved links (recording a DataPackage + provenance), and writes a handoff
manifest per other owner (ytman, Command Center, Nawishtar) into the outbox, so
each app can pick up its slice. Nothing is deleted; the original package is the
source of truth. Chronos computes and prepares — it doesn't reach into other
apps.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..importers.html_import import HTMLImporter
from ..importers.platform.takeout import inspect_takeout

TAKEOUT_PARSER_VERSION = "takeout-1"


@dataclass
class TakeoutResult:
    package_id: int
    already_imported: bool
    ingested_bookmarks: int
    handoffs: Dict[str, str] = field(default_factory=dict)  # owner -> manifest path
    plan_summary: Dict[str, int] = field(default_factory=dict)


class TakeoutService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _read(path: Path, member: str) -> Optional[bytes]:
        p = Path(path)
        if p.is_file() and p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                try:
                    return zf.read(member)
                except KeyError:
                    return None
        f = p / member
        return f.read_bytes() if f.exists() else None

    @staticmethod
    def _hash(path: Path) -> str:
        p = Path(path)
        h = hashlib.sha256()
        if p.is_file():
            h.update(p.read_bytes())
        else:  # folder: hash the sorted listing + sizes (stable enough)
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    h.update(str(f.relative_to(p)).encode())
                    h.update(str(f.stat().st_size).encode())
        return h.hexdigest()

    # -- inspect ------------------------------------------------------------ #
    def inspect(self, path):
        return inspect_takeout(path)

    # -- import + route ----------------------------------------------------- #
    def import_takeout(self, path, ingest: bool = True) -> TakeoutResult:
        path = Path(path)
        plan = inspect_takeout(path)
        sha = self._hash(path)
        pkg_id, seen = self.ctx.provenance.register_package(
            "google_takeout", source_filename=path.name, archive_hash=sha,
            parser_version=TAKEOUT_PARSER_VERSION, retained_path=str(path))

        ingested = 0
        if ingest and not seen:
            ingested = self._ingest_chronos_parts(path, plan, pkg_id)

        handoffs = self._write_handoffs(path, plan, sha)
        self.ctx.storage.update_package_count(
            pkg_id, sum(c.files for c in plan.categories))
        return TakeoutResult(pkg_id, seen, ingested, handoffs, plan.summary())

    def _ingest_chronos_parts(self, path, plan, pkg_id) -> int:
        n = 0
        for cat in plan.for_owner("chronos"):
            # Chrome bookmarks (Netscape HTML)
            for member in cat.members:
                low = member.lower()
                if low.endswith(".html") and "bookmark" in low:
                    raw = self._read(path, member)
                    if not raw:
                        continue
                    tmp = Path(self.ctx.config.app_dir) / "_takeout_bm.html"
                    tmp.write_bytes(raw)
                    try:
                        found = HTMLImporter().parse(tmp)
                        self.ctx.storage.import_bookmarks(found)
                        for b in found:
                            row = self.ctx.storage.get_by_url(b.url)
                            if row and not self.ctx.storage.acquisition_exists(
                                    row.id, "imported", "google_takeout", pkg_id):
                                self.ctx.storage.add_acquisition(
                                    row.id, "imported", "google_takeout",
                                    acquired_at=b.date_added, package_id=pkg_id)
                                n += 1
                    finally:
                        tmp.unlink(missing_ok=True)
        return n

    def _write_handoffs(self, path, plan, sha) -> Dict[str, str]:
        out = Path(self.ctx.config.outbox_dir) / f"takeout-{sha[:8]}"
        handoffs: Dict[str, str] = {}
        for owner in ("ytman", "cc", "nawishtar"):
            cats = plan.for_owner(owner)
            if not cats:
                continue
            out.mkdir(parents=True, exist_ok=True)
            manifest = {
                "target": owner,
                "source": "google_takeout",
                "package": path.name,
                "package_hash": sha,
                "created_at": int(time.time()),
                "categories": [
                    {"product": c.product, "category": c.category,
                     "files": c.files, "bytes": c.bytes, "members": c.members}
                    for c in cats],
                "note": f"{len(cats)} categorie(s) for {owner}; "
                        f"the original package is retained at {path}",
            }
            p = out / f"{owner}.json"
            p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                         encoding="utf-8")
            handoffs[owner] = str(p)
        return handoffs
