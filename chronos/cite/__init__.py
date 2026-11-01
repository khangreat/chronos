"""Citations out — your items, with your quotes and takeaways, in the tools you
write and read with.

- `zotero`  — straight into Zotero 7 on this computer (its connector, as the
  browser extension uses it). Nothing leaves your computer.
- `reading` — clean snapshots for Nawishtar's Reading folder: the tags
  Nawishtar reads (title, address, author, site, published, archived), one
  paragraph per paragraph so "para. 3" means what it says.
- `epub`    — a reading book for Khwānōk (or any e-reader): the items you pick
  as chapters, each with where it came from and your own notes.

All three read the same record of an item, built here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..core.models import Bookmark

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: Optional[str]) -> str:
    """Text safe for XML: no control characters, newlines normalised."""
    return _CONTROL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n"))


def is_web(url: Optional[str]) -> bool:
    return bool(url) and url.lower().startswith(("http://", "https://"))


def iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def archived_at(ctx, bm: Bookmark) -> Optional[int]:
    """When Chronos kept this item: its offline copy, else when it was read,
    else when it was saved."""
    rec = ctx.storage.get_archive(bm.id) if ctx.archive.has_archive(bm.id) else None
    ts = (rec.get("archived_at") if isinstance(rec, dict)
          else getattr(rec, "archived_at", None)) if rec else None
    return ts or bm.fetched_at or bm.date_added


def paragraphs(ctx, bm: Bookmark) -> List[str]:
    """The item's readable text as paragraphs (offline; never fetches)."""
    text = bm.page_text or ""
    if not text.strip() and ctx.archive.has_archive(bm.id):
        from ..web.extract import extract_content
        try:
            text = extract_content(ctx.archive.read_html(bm.id) or "", bm.url).text or ""
        except Exception:
            text = ""
    if not text.strip():
        text = bm.excerpt or ""
    title = (bm.page_title or bm.title or "").strip()
    out = []
    for line in clean(text).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line and line != title:
            out.append(line)
    return out


def record(ctx, bm: Bookmark) -> Dict:
    """Everything the outbound formats share about one item."""
    return {
        "id": bm.id, "title": (bm.page_title or bm.title or bm.url or "").strip(),
        "url": bm.url if is_web(bm.url) else None, "kind": bm.kind or "webpage",
        "author": bm.byline, "site": bm.site_name, "excerpt": bm.excerpt,
        "published": bm.published_ts, "saved": bm.date_added,
        "archived": archived_at(ctx, bm), "wayback": bm.wayback_url,
        "tags": list(bm.tags or []),
        "quotes": [q.quote for q in ctx.snippets.for_bookmark(bm.id)],
        "takeaways": [t.text for t in ctx.takeaways.for_bookmark(bm.id)],
    }


def items(ctx, ids: Optional[List[int]]) -> List[Bookmark]:
    if ids is None:
        return ctx.storage.all_bookmarks()
    return [b for b in (ctx.storage.get(i) for i in ids) if b is not None]
