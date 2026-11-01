"""Facebook "Download Your Information" (JSON) parser.

Reads an extracted export folder or the .zip itself. Handles:
  - your posts         -> posts with text, time, and any shared link
  - saved items        -> links you saved on Facebook
  - comments           -> comments you wrote, with the post title they were on
  - group posts        -> posts you made in groups

Facebook writes UTF-8 text as escaped Latin-1 code units, so non-Latin text
arrives as mojibake ("Ø§Ù„" for "ال"). `fix_text` repairs it — essential for
Urdu, Arabic, Brahui and any non-English content.

Your own posts have no public permalink in the export, so they get a stable
local id (fb-post://…); a link you shared becomes its own resource, related to
the post. Likes and reactions carry no link or text in the export and are not
imported (nothing usable to archive).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple


@dataclass
class FacebookItem:
    kind: str                    # "post" | "saved" | "comment"
    url: str                     # real link, or fb-post:// / fb-comment:// id
    title: str
    text: str
    timestamp: Optional[int]
    shared_url: Optional[str] = None
    extra: dict = field(default_factory=dict)


def fix_text(s: Optional[str]) -> str:
    """Undo Facebook's double-encoding; leave correct text untouched."""
    if not s:
        return ""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _iter_json(path: Path) -> Iterator[Tuple[str, object]]:
    """Yield (relative_path, parsed_json) for every .json in a folder or zip."""
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".json"):
                    try:
                        yield name, json.loads(zf.read(name).decode("utf-8"))
                    except ValueError:
                        continue
    elif path.is_dir():
        for f in path.rglob("*.json"):
            try:
                yield str(f.relative_to(path)), json.loads(f.read_text("utf-8"))
            except ValueError:
                continue
    elif path.suffix.lower() == ".json":
        try:
            yield path.name, json.loads(path.read_text("utf-8"))
        except ValueError:
            return


def _sid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _external_url(attachments) -> Tuple[Optional[str], str]:
    for att in attachments or []:
        for d in att.get("data", []) if isinstance(att, dict) else []:
            ec = d.get("external_context") if isinstance(d, dict) else None
            if isinstance(ec, dict) and ec.get("url"):
                return ec["url"], fix_text(ec.get("name") or "")
    return None, ""


def _post_text(entry: dict) -> str:
    for d in entry.get("data", []) or []:
        if isinstance(d, dict) and d.get("post"):
            return fix_text(d["post"])
    return ""


def _parse_posts(data) -> List[FacebookItem]:
    out = []
    rows = data if isinstance(data, list) else []
    for e in rows:
        if not isinstance(e, dict):
            continue
        text = _post_text(e)
        shared, shared_name = _external_url(e.get("attachments"))
        title = fix_text(e.get("title") or "")
        if not text and not shared:
            continue                              # photo-only / empty: nothing to keep
        ts = e.get("timestamp")
        out.append(FacebookItem(
            kind="post", url=f"fb-post://{_sid(ts, text, shared)}",
            title=(text.splitlines()[0][:80] if text else (shared_name or title
                                                           or "Facebook post")),
            text=text, timestamp=ts, shared_url=shared,
            extra={"shared_name": shared_name, "context": title}))
    return out


def _parse_saved(data) -> List[FacebookItem]:
    rows = []
    if isinstance(data, dict):
        rows = data.get("saves_v2") or data.get("saves") or []
    out = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        url, name = _external_url(e.get("attachments"))
        if not url:
            continue
        out.append(FacebookItem(
            kind="saved", url=url, title=name or fix_text(e.get("title") or url),
            text="", timestamp=e.get("timestamp")))
    return out


def _parse_comments(data) -> List[FacebookItem]:
    rows = []
    if isinstance(data, dict):
        rows = data.get("comments_v2") or data.get("comments") or []
    out = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        text = ""
        for d in e.get("data", []) or []:
            c = d.get("comment") if isinstance(d, dict) else None
            if isinstance(c, dict) and c.get("comment"):
                text = fix_text(c["comment"])
        if not text:
            continue
        ts = e.get("timestamp")
        out.append(FacebookItem(
            kind="comment", url=f"fb-comment://{_sid(ts, text)}",
            title=text.splitlines()[0][:80],
            text=text, timestamp=ts,
            extra={"context": fix_text(e.get("title") or "")}))
    return out


def parse_facebook(path) -> List[FacebookItem]:
    """Parse every recognised file in a Facebook export."""
    items: List[FacebookItem] = []
    for rel, data in _iter_json(Path(path)):
        low = rel.lower().replace("\\", "/")
        name = low.rsplit("/", 1)[-1]
        if "group" in name and "post" in name:          # before "comments" below
            rows = data.get("group_posts_v2") or data.get("group_posts") \
                if isinstance(data, dict) else data
            for it in _parse_posts(rows or []):
                it.extra["group"] = True
                items.append(it)
        elif "saved_items" in low or name.startswith("your_saved_items"):
            items += _parse_saved(data)
        elif "comments" in name and "reaction" not in name:
            items += _parse_comments(data)
        elif "/posts/" in f"/{low}" and name.startswith("your_posts"):
            items += _parse_posts(data)

    return items
