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

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from ..importers.platform.takeout import inspect_takeout

TAKEOUT_PARSER_VERSION = "takeout-2"


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

    # -- inspect ------------------------------------------------------------ #
    def inspect(self, path):
        return inspect_takeout(path)

    # -- import + route ----------------------------------------------------- #
    def import_takeout(self, path, ingest: bool = True) -> TakeoutResult:
        """A Takeout — one .zip, a folder of parts, a .tgz. Chronos keeps its
        parts (Chrome bookmarks, reading list and history, Google searches and
        Chrome activity, Saved links) and prepares the rest for its owners."""
        from .universal_import import fast_hash
        path = Path(path)
        sha = fast_hash(path)
        pkg_id, seen = self.ctx.provenance.register_package(
            "google_takeout", source_filename=path.name, archive_hash=sha,
            parser_version=TAKEOUT_PARSER_VERSION, retained_path=str(path))
        found = 0
        handoffs: Dict[str, str] = {}
        summary: Dict[str, int] = {}
        if ingest and not seen:
            rep = self.ctx.universal.import_paths([path], package_id=pkg_id)
            found = rep.found
            handoffs = rep.handoffs
        if not handoffs:
            handoffs = self.prepare_handoffs(path)
        plan = inspect_takeout(path) if not path.name.lower().endswith((".tgz", ".gz", ".tar")) \
            else None
        if plan is not None:
            summary = plan.summary()
            self.ctx.storage.update_package_count(pkg_id, sum(c.files for c in plan.categories))
        return TakeoutResult(pkg_id, seen, found, handoffs, summary)

    def prepare_handoffs(self, path) -> Dict[str, str]:
        """Write a manifest for each other app that owns part of this Takeout."""
        from .universal_import import fast_hash
        path = Path(path)
        return self._write_handoffs(path, inspect_takeout(path), fast_hash(path))

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
