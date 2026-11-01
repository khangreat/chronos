"""Open anything: a file, a folder, a .zip or .tgz (or several), zips inside
zips — and say what each file inside is.

Files are recognised by what they contain, not where they sit: Google names
Takeout folders in your account's language ("Chrome", "Verlauf", "سجل التصفح"…),
Reddit and Facebook rename theirs over time. So a bookmarks file is a bookmarks
file because it says `NETSCAPE-Bookmark-file`, a Chrome history because its JSON
holds "Browser History", and so on.

Nothing is loaded whole that needn't be: archives are read member by member, a
.tgz is streamed and only the kinds of files Chronos can use are unpacked, and
huge JSON arrays (a decade of browsing) are read one record at a time.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

# Files worth opening at all; everything else (photos, videos, mail…) is counted
# as "not something Chronos keeps" without being read.
USEFUL_EXT = {".html", ".htm", ".json", ".csv", ".txt", ".js", ".car", ".sqlite",
              ".db", ".zip", ".tgz", ".gz", ".tar"}
USEFUL_NAMES = {"bookmarks", "history", "places.sqlite"}       # browser files, no extension
ARCHIVE_EXT = (".zip", ".tgz", ".tar.gz", ".tar")
MAX_DEPTH = 3                                                  # zips inside zips inside…


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("/")


def is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_EXT)


def useful(name: str) -> bool:
    low = name.lower().rsplit("/", 1)[-1]
    return low in USEFUL_NAMES or os.path.splitext(low)[1] in USEFUL_EXT \
        or low.endswith(".tar.gz")


@dataclass
class Entry:
    rel: str                        # path inside its container, "/"-separated
    size: int
    container: Path                 # the zip / folder / file it lives in (on disk)
    _open: Callable[[], io.BufferedIOBase]

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def low(self) -> str:
        return self.rel.lower()

    def read(self) -> bytes:
        with self._open() as f:
            return f.read()

    def head(self, n: int = 4096) -> bytes:
        with self._open() as f:
            return f.read(n)

    def to_file(self, folder: Path) -> Path:
        """Copy to a real file (for readers that need a path), streamed."""
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"{abs(hash(self.rel)) % 10**10}_{self.name}"
        with self._open() as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        return out


def _tar_unpack(path: Path, dest: Path, skipped=None) -> Path:
    """Stream a .tgz/.tar and unpack only useful members (never media) — safely:
    no absolute paths, no '..', no links."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "r|*") as tf:
        for m in tf:
            if not m.isfile():
                continue
            if not useful(m.name):
                if skipped:
                    skipped(m.name)
                continue
            rel = _norm(m.name)
            if rel.startswith("/") or ".." in rel.split("/"):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            with src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    return dest


def walk(paths, work: Path, depth: int = 0, skipped=None) -> Iterator[Entry]:
    """Every file inside `paths`, opening archives (and archives inside them).
    `skipped(rel)` is told about files not worth opening."""
    for path in paths:
        path = Path(path)
        low = path.name.lower()
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if not f.is_file():
                    continue
                rel = _norm(str(f.relative_to(path)))
                if is_archive(f.name) and depth < MAX_DEPTH:
                    yield from walk([f], work, depth + 1, skipped)
                elif useful(rel):
                    yield Entry(rel, f.stat().st_size, path,
                                (lambda f=f: open(f, "rb")))
                elif skipped:
                    skipped(rel)
        elif low.endswith(".zip") and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    rel = _norm(info.filename)
                    if is_archive(rel) and depth < MAX_DEPTH:
                        inner = work / f"nested{depth}_{abs(hash((str(path), rel))) % 10**10}"
                        inner.mkdir(parents=True, exist_ok=True)
                        tmp = inner / rel.rsplit("/", 1)[-1]
                        with zf.open(info) as src, open(tmp, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        yield from walk([tmp], work, depth + 1, skipped)
                    elif useful(rel):
                        yield Entry(rel, info.file_size, path,
                                    (lambda zf=zf, info=info: zf.open(info)))
                    elif skipped:
                        skipped(rel)
        elif low.endswith((".tgz", ".tar.gz", ".tar")) and tarfile.is_tarfile(path):
            folder = _tar_unpack(path, work / f"untar{depth}_{abs(hash(str(path))) % 10**10}",
                                 skipped)
            yield from walk([folder], work, depth + 1, skipped)
        elif path.is_file():
            yield Entry(path.name, path.stat().st_size, path,
                        (lambda p=path: open(p, "rb")))


# --------------------------------------------------------------------------- #
# What is this file?
# --------------------------------------------------------------------------- #
SQLITE_MAGIC = b"SQLite format 3\x00"


def kind_of(e: Entry) -> str:
    """Recognise one file by its name and first bytes."""
    name, low = e.name.lower(), e.low
    try:
        head = e.head(8192)
    except OSError:
        return "unreadable"
    text = head.decode("utf-8", "replace").lstrip("﻿ \r\n\t")
    tl = text.lower()
    if head.startswith(SQLITE_MAGIC):
        return "sqlite"
    if name.endswith(".car"):
        return "bluesky"
    if name.endswith(".chronos.json"):
        return "capture"
    if name.endswith((".html", ".htm")):
        if "netscape-bookmark-file" in tl or re.search(r"<dt>\s*<a\s+href", tl):
            return "bookmarks_html"
        if "pocket export" in tl or "time_added=" in tl:
            return "pocket_html"
        if "outer-cell" in tl or "mdl-grid" in tl:
            return "activity_html"
        if "facebook" in low or "your_facebook_activity" in low:
            return "facebook_html"
        return "other"
    if name.endswith(".js"):
        if "window.ytd." in tl:
            return "x"
        return "other"
    if name.endswith(".json") or name == "bookmarks":
        if '"browser history"' in tl:
            return "chrome_history"
        if '"roots"' in tl and ('"bookmark_bar"' in tl or '"checksum"' in tl):
            return "chromium_bookmarks"
        if tl.startswith("[") and '"header"' in tl and '"time"' in tl:
            return "activity"
        if '"kind": "listing"' in tl or '"kind":"listing"' in tl \
                or re.search(r'"kind":\s*"t[13]"', tl):
            return "reddit_listing"
        if '"ordereditems"' in tl and ("outbox" in name or "activitystreams" in tl):
            return "mastodon"
        if any(k in low for k in ("your_facebook_activity", "your_activity_across_facebook")) \
                or name.startswith(("your_posts", "your_saved_items", "group_posts")):
            return "facebook"
        return "other"
    if name.endswith(".csv"):
        first = tl.split("\n", 1)[0]
        cols = [c.strip().strip('"') for c in first.split(",")]
        if "permalink" in cols:
            return "reddit_export"
        if "channel id" in cols or "video id" in cols:
            return "youtube"
        if any(c in ("url", "link", "href", "address") for c in cols):
            return "links_csv"
        return "other"
    if name.endswith(".txt"):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        urls = [ln for ln in lines if re.match(r"https?://", ln)]
        if urls and len(urls) * 2 >= len(lines):
            return "links_txt"
        return "other"
    return "other"


# --------------------------------------------------------------------------- #
# Big JSON, one record at a time
# --------------------------------------------------------------------------- #
def iter_array(text: str, key: Optional[str] = None) -> Iterator[dict]:
    """Yield the objects of a JSON array — the top-level one, or the one under
    `key` — without building the whole list in memory."""
    dec = json.JSONDecoder()
    if key is None:
        i = text.find("[")
    else:
        m = re.search(r'"%s"\s*:\s*\[' % re.escape(key), text)
        i = m.end() - 1 if m else -1
    if i < 0:
        return
    i += 1
    n = len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t,":
            i += 1
        if i >= n or text[i] == "]":
            return
        obj, i = dec.raw_decode(text, i)
        if isinstance(obj, dict):
            yield obj


def unwrap_google(url: str) -> str:
    """https://www.google.com/url?q=https://real.page/&usg=… → https://real.page/"""
    from urllib.parse import parse_qs, urlsplit
    p = urlsplit(url or "")
    if "google." in (p.hostname or "") and p.path == "/url":
        q = parse_qs(p.query).get("q") or parse_qs(p.query).get("url")
        if q and q[0].startswith(("http://", "https://")):
            return q[0]
    return url
