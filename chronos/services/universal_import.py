"""Import anything — one door for every file, folder and archive you have.

Hand it what you downloaded — a Google Takeout (one zip or all its parts, or a
.tgz), a Reddit / X / Facebook / Mastodon / Bluesky export, a browser's
bookmarks.html or History file, a Pocket / Raindrop / Instapaper / Google Saved
CSV, a OneTab list, a folder holding several of these, zips inside zips — and
it keeps everything Chronos can keep, hands the rest of a Takeout to the app
that owns it, and says plainly what it read and what it left, and why.

Nothing is fetched; nothing you picked is changed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from ..core.models import Bookmark
from ..importers.anything import Entry, iter_array, kind_of, unwrap_google, walk

PARSER_VERSION = "anything-1"

# Why a file was left: shown to the person, so in plain words.
WHY = {
    "activity_html": "Google activity saved as HTML — export “My Activity” "
                     "as JSON in Takeout to bring it in",
    "facebook_html": "Facebook export in HTML — download it again choosing JSON",
    "youtube": "YouTube history, searches and subscriptions — these belong to ytman",
    "activity_other": "other Google activity (Maps, Play, Assistant…) — not web pages",
    "other": "files that aren’t bookmarks, history or posts",
    "media": "photos, videos, mail and documents — not something Chronos keeps",
    "unreadable": "files that couldn’t be read",
}


@dataclass
class ImportReport:
    read: "OrderedDict[str, List[int]]" = field(default_factory=OrderedDict)  # what -> [found, new]
    skipped: Dict[str, int] = field(default_factory=dict)                   # reason -> files/records
    handoffs: Dict[str, str] = field(default_factory=dict)                  # app -> manifest
    problems: List[str] = field(default_factory=list)

    def add(self, what: str, found: int, new: int) -> None:
        cur = self.read.setdefault(what, [0, 0])
        cur[0] += found; cur[1] += new

    def skip(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n

    @property
    def found(self) -> int:
        return sum(v[0] for v in self.read.values())

    @property
    def new(self) -> int:
        return sum(v[1] for v in self.read.values())

    def text(self) -> str:
        lines = []
        if self.read:
            lines.append(f"Brought in {self.found:,} item{'s' if self.found != 1 else ''}, "
                         f"{self.new:,} new to your archive:")
            lines += [f"  • {w}: {f:,} found, {n:,} new" for w, (f, n) in self.read.items()]
        else:
            lines.append("Nothing Chronos keeps was found here.")
        if self.handoffs:
            names = {"ytman": "ytman", "cc": "Command Center", "nawishtar": "Nawishtar"}
            lines.append("Prepared for your other apps: "
                         + ", ".join(names.get(k, k) for k in self.handoffs) + ".")
        if self.skipped:
            lines.append("Left out:")
            lines += [f"  • {WHY.get(r, r)}: {n:,}" for r, n in
                      sorted(self.skipped.items(), key=lambda kv: -kv[1])]
        if self.problems:
            lines.append("Problems:")
            lines += [f"  • {p}" for p in self.problems]
        return "\n".join(lines)


def _ts_iso(v) -> Optional[int]:
    if v in (None, ""):
        return None
    s = str(v).strip()
    if s.isdigit():
        n = int(s)
        return n // 1000 if n > 10**11 else n          # ms → s
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return int(datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _web(url: str) -> bool:
    return bool(url) and url.startswith(("http://", "https://"))


class UniversalImportService:
    def __init__(self, ctx):
        self.ctx = ctx

    # ------------------------------------------------------------------ #
    def import_paths(self, paths, progress: Optional[Callable[[str], None]] = None,
                     package_id: Optional[int] = None) -> ImportReport:
        paths = [Path(p) for p in (paths if isinstance(paths, (list, tuple)) else [paths])]
        for p in paths:
            if not p.exists():
                raise FileNotFoundError(f"Not found: {p}")
        if package_id is None:
            h = hashlib.sha256("|".join(fast_hash(p) for p in paths).encode()).hexdigest()
            package_id, _ = self.ctx.provenance.register_package(
                "files", source_filename=", ".join(p.name for p in paths)[:240],
                archive_hash=h, parser_version=PARSER_VERSION,
                retained_path=str(paths[0]) if len(paths) == 1 else None)
        self._pkg = package_id
        rep = ImportReport()
        work = Path(tempfile.mkdtemp(prefix="chronos_import_"))
        platforms: Dict[str, "OrderedDict[Path, None]"] = {}
        takeouts: "OrderedDict[Path, None]" = OrderedDict()
        try:
            def media(rel):
                rep.skip("media")
            for e in walk(paths, work, skipped=media):
                if e.low.startswith("takeout/") or "/takeout/" in "/" + e.low:
                    takeouts[e.container] = None
                k = kind_of(e)
                if progress:
                    progress(e.rel)
                try:
                    self._one(e, k, rep, platforms, work)
                except Exception as ex:                   # one bad file never stops the rest
                    rep.problems.append(f"{e.rel}: {ex}")
            for plat, containers in platforms.items():
                for c in containers:
                    self._platform(plat, c, rep)
            for c in takeouts:
                self._takeout_handoffs(c, rep)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return rep

    # ------------------------------------------------------------------ #
    def _one(self, e: Entry, k: str, rep: ImportReport, platforms, work: Path) -> None:
        if k in ("reddit_export", "x", "facebook", "mastodon", "bluesky"):
            container = e.container
            if k == "bluesky" and not e.container.name.lower().endswith(".car"):
                container = e.to_file(work / "car")
            platforms.setdefault(k, OrderedDict())[container] = None
            return
        handler = getattr(self, f"_k_{k}", None)
        if handler is None:
            rep.skip(k if k in WHY else "other")
            return
        handler(e, rep, work)

    def _store(self, what: str, items: List[Bookmark], method: str, source: str,
               rep: ImportReport, detail: Optional[dict] = None) -> None:
        if not items:
            return
        st = self.ctx.storage
        new = 0
        for b in items:
            bid, was_new = st.upsert_bookmark(b)
            new += int(was_new)
            self.ctx.provenance.record(bid, method, source=source, acquired_at=b.date_added,
                                       detail=detail, package_id=getattr(self, "_pkg", None),
                                       commit=False)
        st.conn.commit()                                   # one write for the whole file
        rep.add(what, len(items), new)

    # -- browsers ----------------------------------------------------------- #
    def _browser_label(self, e: Entry) -> str:
        return "Chrome" if ("takeout/" in e.low) else "HTML"

    def _k_bookmarks_html(self, e, rep, work):
        from ..importers.html_import import HTMLImporter
        found = HTMLImporter().parse(e.to_file(work / "html"))
        label = self._browser_label(e)
        reading = "reading" in e.name.lower()
        for b in found:
            b.browser = label
            if reading and not b.folder_name:
                b.folder_name = "Reading list"
        what = ("Chrome reading list" if reading else "Chrome bookmarks") \
            if label == "Chrome" else "Bookmarks (HTML file)"
        self._store(what, found, "imported",
                    "google_takeout" if label == "Chrome" else "html", rep)

    def _k_pocket_html(self, e, rep, work):
        text = e.read().decode("utf-8", "replace")
        out = []
        for m in re.finditer(r'<a\s+([^>]*)>(.*?)</a>', text, re.I | re.S):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
            url = attrs.get("href", "")
            if not _web(url):
                continue
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip() or url
            tags = [t for t in attrs.get("tags", "").split(",") if t]
            out.append(Bookmark(url=url, title=title, browser="Pocket",
                                date_added=_ts_iso(attrs.get("time_added")) or 0, tags=tags))
        self._store("Pocket", out, "imported", "pocket", rep)

    def _k_chromium_bookmarks(self, e, rep, work):
        from ..importers.chromium import ChromiumImporter
        found = ChromiumImporter().parse(e.to_file(work / "cb"))
        for b in found:
            b.browser = "Chrome"
        self._store("Chrome bookmarks (file)", found, "browser_bookmark", "chrome", rep)

    def _k_chrome_history(self, e, rep, work):
        text = e.read().decode("utf-8", "replace")
        latest: Dict[str, Bookmark] = {}
        for r in iter_array(text, "Browser History"):
            url = r.get("url") or ""
            if not _web(url):
                continue
            ts = int(r.get("time_usec") or 0) // 1_000_000
            cur = latest.get(url)
            if cur is None or ts > cur.date_added:
                latest[url] = Bookmark(url=url, title=(r.get("title") or url).strip(),
                                       date_added=ts, browser="Chrome history")
        self._store("Chrome history (Takeout)", list(latest.values()),
                    "browser_history", "google_takeout", rep)

    def _k_sqlite(self, e, rep, work):
        import sqlite3
        f = e.to_file(work / "db")
        con = sqlite3.connect(str(f))
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        if "moz_places" in tables:
            from ..importers.firefox import FirefoxImporter
            from ..importers.history import FirefoxHistoryImporter
            self._store("Firefox bookmarks (file)", FirefoxImporter().parse(f),
                        "browser_bookmark", "firefox", rep)
            self._store("Firefox history (file)", FirefoxHistoryImporter().parse(f),
                        "browser_history", "firefox", rep)
        elif {"urls", "visits"} <= tables:
            from ..importers.history import ChromiumHistoryImporter
            imp = ChromiumHistoryImporter(); imp.name = "Chrome history"
            self._store("Chrome history (file)", imp.parse(f), "browser_history", "chrome", rep)
        else:
            rep.skip("other")        # cookies, logins, caches: never read

    # -- Google activity ---------------------------------------------------- #
    def _k_activity(self, e, rep, work):
        text = e.read().decode("utf-8", "replace")
        visits: Dict[str, Bookmark] = {}
        searches: Dict[str, Bookmark] = {}
        yt = other = 0
        for r in iter_array(text):
            products = [p.lower() for p in (r.get("products") or [])]
            header = (r.get("header") or "").lower()
            url = r.get("titleUrl") or ""
            ts = _ts_iso(r.get("time")) or 0
            if "youtube" in products or "youtube" in header:
                yt += 1
                continue
            if not _web(url):
                other += 1
                continue
            parts = urlsplit(url)
            q = parse_qs(parts.query).get("q", [""])[0]
            if ("search" in products or header == "search") and "google." in (parts.hostname or "") \
                    and parts.path.startswith("/search") and q:
                b = searches.get(q)
                if b is None or ts > b.date_added:
                    searches[q] = Bookmark(url=url, title=q, date_added=ts,
                                           browser="Google Search", site_name="Google Search",
                                           kind="search")
            elif "chrome" in products or header == "chrome":
                real = unwrap_google(url)
                title = (r.get("title") or real)
                title = title[len("Visited "):] if title.startswith("Visited ") else title
                b = visits.get(real)
                if b is None or ts > b.date_added:
                    visits[real] = Bookmark(url=real, title=title, date_added=ts,
                                            browser="Chrome history")
            else:
                other += 1
        self._store("Chrome activity (Takeout)", list(visits.values()),
                    "browser_history", "google_takeout", rep)
        self._store("Google searches (Takeout)", list(searches.values()),
                    "imported", "google_takeout", rep)
        if yt:
            rep.skip("youtube", yt)
        if other:
            rep.skip("activity_other", other)

    # -- lists of links ------------------------------------------------------ #
    def _k_links_csv(self, e, rep, work):
        text = e.read().decode("utf-8-sig", "replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return
        cols = {(k or "").strip().lower(): k for k in rows[0].keys()}
        g = lambda r, *names: next(((r.get(cols[n]) or "").strip()            # noqa: E731
                                    for n in names if n in cols and (r.get(cols[n]) or "").strip()), "")
        keys = set(cols)
        if {"time_added", "status"} <= keys:
            label, src = "Pocket", "pocket"
        elif {"cover", "highlights"} & keys or {"excerpt", "folder", "created"} <= keys:
            label, src = "Raindrop", "raindrop"
        elif {"selection", "folder", "timestamp"} <= keys:
            label, src = "Instapaper", "instapaper"
        elif {"title", "note", "url"} <= keys and len(keys) <= 5:
            label, src = "Google Saved", "google_saved"
        else:
            label, src = "Links file", "links"
        stem = e.name.rsplit(".", 1)[0]
        out = []
        for r in rows:
            url = g(r, "url", "link", "href", "address")
            if not _web(url):
                continue
            tags_raw = g(r, "tags", "tag", "labels")
            tags = [t.strip() for t in re.split(r"[|,]", tags_raw) if t.strip()]
            folder = g(r, "folder", "collection", "list") or (stem if src == "google_saved" else None)
            out.append(Bookmark(
                url=url, title=g(r, "title", "name") or url, browser=label,
                date_added=_ts_iso(g(r, "time_added", "created", "timestamp", "date",
                                     "added", "date_added")) or 0,
                folder_name=folder or None, tags=tags,
                notes=g(r, "note", "comment", "excerpt", "selection", "description")))
        self._store(label if label != "Links file" else f"Links ({e.name})", out,
                    "imported", src, rep)

    def _k_links_txt(self, e, rep, work):
        text = e.read().decode("utf-8", "replace")
        out = []
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"(https?://\S+)(?:\s*\|\s*(.*))?$", line)
            if m:
                out.append(Bookmark(url=m.group(1), title=(m.group(2) or m.group(1)).strip(),
                                    date_added=0, browser="Links file"))
        label = "OneTab" if any(" | " in ln for ln in text.splitlines()[:50]) else f"Links ({e.name})"
        self._store(label, out, "imported", "links", rep)

    # -- Reddit, read in the browser or saved by hand ------------------------ #
    def _k_reddit_listing(self, e, rep, work):
        from ..importers.platform.reddit_listing import parse_listing
        items = parse_listing(json.loads(e.read().decode("utf-8", "replace")))
        r = self.ctx.platform_import.import_reddit_items(items, label=e.name)
        rep.add("Reddit", r.resources, r.new_resources)

    def _k_capture(self, e, rep, work):
        r = self.ctx.capture.ingest_json(e.read().decode("utf-8", "replace"))
        rep.add("Captures", 1, int(bool(getattr(r, "new_resource", False))))

    # -- whole exports -------------------------------------------------------- #
    def _platform(self, plat: str, container: Path, rep: ImportReport) -> None:
        pi = self.ctx.platform_import
        fn, what = {"reddit_export": (pi.import_reddit, "Reddit"),
                    "x": (pi.import_x, "X"), "facebook": (pi.import_facebook, "Facebook"),
                    "mastodon": (pi.import_mastodon, "Mastodon"),
                    "bluesky": (pi.import_bluesky, "Bluesky")}[plat]
        try:
            r = fn(container)
        except ValueError as ex:
            rep.problems.append(f"{what} ({container.name}): {ex}")
            return
        rep.add(what, r.resources, r.new_resources)

    def _takeout_handoffs(self, container: Path, rep: ImportReport) -> None:
        try:
            r = self.ctx.takeout.prepare_handoffs(container)
        except Exception as ex:
            rep.problems.append(f"Takeout ({container.name}): {ex}")
            return
        rep.handoffs.update(r)


BIG = 256 << 20


def fast_hash(path: Path) -> str:
    """Identity of a file or folder without reading gigabytes: a file's bytes
    (streamed) — or, past 256 MB, its name, size and first and last megabyte —
    or a folder's names, sizes and the first 64 KB of each file."""
    h = hashlib.sha256()
    path = Path(path)
    if path.is_file():
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > BIG:
                h.update(f"{path.name}|{size}".encode())
                h.update(f.read(1 << 20))
                f.seek(size - (1 << 20))
                h.update(f.read(1 << 20))
            else:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        return h.hexdigest()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(path)).replace("\\", "/").encode())
            h.update(str(f.stat().st_size).encode())
            with open(f, "rb") as fh:
                h.update(fh.read(65536))
    return h.hexdigest()
