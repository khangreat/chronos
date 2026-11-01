"""CaptureService — ingest a live capture from the browser.

A capture is a small JSON object a front-end (bookmarklet, GUI paste, or a future
extension) produces while you browse: the specific post/page URL, its text, your
selection, and the page you found it on. Ingesting it creates or updates the
resource with the right kind, records a `manual_capture` acquisition, turns any
selection into a quote, links it to the source page, and auto-tags it.

The capture format (all fields optional except url):
    {
      "url": "https://x.com/user/status/123",   # the specific post/page
      "title": "...", "text": "...", "selection": "...",
      "author": "...", "site_name": "...", "kind": "social_post",
      "source_page": "https://x.com/home",        # where you found it
      "tags": ["..."], "captured_at": 1700000000
    }
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from ..core.models import Bookmark


@dataclass
class CaptureRecord:
    url: str
    title: str = ""
    text: str = ""
    selection: str = ""
    author: str = ""
    site_name: str = ""
    kind: str = ""
    source_page: str = ""
    description: str = ""
    published: str = ""              # ISO 8601 or epoch string; parsed on ingest
    tags: List[str] = field(default_factory=list)
    captured_at: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CaptureRecord":
        keys = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class CaptureResult:
    bookmark_id: int
    kind: str
    quoted: bool
    new_resource: bool


def _parse_published(value) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    if s.isdigit():
        return int(s)
    from ..importers.platform._social import iso_ts
    return iso_ts(s)


def infer_kind(url: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path
    if any(h in host for h in ("x.com", "twitter.com")) and "/status/" in path:
        return "social_post"
    if "reddit.com" in host and "/comments/" in path:
        # a trailing comment id after the slug means it's a comment
        segs = [s for s in path.split("/") if s]
        if "comments" in segs and len(segs) - segs.index("comments") > 3:
            return "social_comment"
        return "social_post"
    if any(h in host for h in ("mastodon", "bsky.app", "threads.net")):
        return "social_post"
    return "webpage"


class CaptureService:
    def __init__(self, ctx):
        self.ctx = ctx

    def ingest(self, cap: CaptureRecord) -> CaptureResult:
        if not cap.url:
            raise ValueError("Capture has no url.")
        kind = infer_kind(cap.url, cap.kind)
        host = urlsplit(cap.url).hostname or ""
        published_ts = _parse_published(cap.published)
        existing = self.ctx.storage.get_by_url(cap.url)
        if existing is None:
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=cap.url, title=cap.title or host,
                date_added=cap.captured_at or int(time.time()),
                browser="Capture", site_name=cap.site_name or host,
                byline=cap.author or None, page_text=cap.text or None,
                excerpt=cap.description or None, published_ts=published_ts,
                kind=kind))
            new = True
        else:
            bid = existing.id
            self.ctx.storage.set_kind(bid, kind)
            new = False
        # best-ref: fill any missing author/site/date/description
        self.ctx.storage.enrich_metadata(bid, {
            "author": cap.author, "site_name": cap.site_name,
            "description": cap.description, "published_ts": published_ts})

        # provenance: this was a deliberate manual capture
        self.ctx.provenance.record(
            bid, "manual_capture", source=host or "browser",
            detail={"source_page": cap.source_page, "author": cap.author})

        # selection → quote
        quoted = False
        if cap.selection.strip():
            try:
                self.ctx.snippets.capture(bid, cap.selection.strip())
                quoted = True
            except Exception:
                pass

        # link to the page it was found on
        if cap.source_page and cap.source_page != cap.url:
            src = self.ctx.storage.get_by_url(cap.source_page)
            if src is None:
                sbid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                    url=cap.source_page, title=urlsplit(cap.source_page).hostname or "",
                    date_added=cap.captured_at or int(time.time()),
                    browser="Capture", kind="webpage"))
            else:
                sbid = src.id
            self.ctx.resources.relate(bid, sbid, "related")

        if cap.tags:
            merged = sorted(set(self.ctx.storage.get(bid).tags) | set(cap.tags))
            self.ctx.storage.set_tags(bid, merged)
        else:
            try:
                self.ctx.tagging.auto_tag(bid)
            except Exception:
                pass

        return CaptureResult(bid, kind, quoted, new)

    def ingest_json(self, text: str) -> CaptureResult:
        return self.ingest(CaptureRecord.from_dict(json.loads(text)))

    def ingest_inbox(self, folder=None) -> int:
        """Ingest every *.chronos.json (or *.json) capture file in a folder,
        moving processed files into a `processed/` subfolder. Defaults to the
        app inbox dir."""
        folder = Path(folder) if folder else Path(self.ctx.config.inbox_dir)
        folder.mkdir(parents=True, exist_ok=True)
        done = folder / "processed"
        n = 0
        files = sorted(list(folder.glob("*.chronos.json")) + list(folder.glob("*.json")))
        for f in files:
            try:
                self.ingest_json(f.read_text(encoding="utf-8"))
                n += 1
            except Exception:
                continue
            try:
                done.mkdir(exist_ok=True)
                f.rename(done / f.name)
            except OSError:
                pass
        return n


# --------------------------------------------------------------------------- #
# Bookmarklet — the zero-install browser front-end
# --------------------------------------------------------------------------- #
def bookmarklet() -> str:
    """A javascript: bookmarklet that captures the specific post/page under the
    selection and downloads a capture file for Chronos to ingest."""
    js = (
        "(function(){"
        "var s=window.getSelection?window.getSelection().toString():'';"
        "var u=location.href,sp='';"
        # best-effort: find the specific post permalink near the selection
        "try{var n=window.getSelection().anchorNode;"
        "var e=n&&n.nodeType===3?n.parentElement:n;"
        "while(e){var a=e.querySelector?e.querySelector"
        "(\"a[href*='/status/'],a[href*='/comments/']\"):null;"
        "if(a){u=a.href;sp=location.href;break;}e=e.parentElement;}}catch(x){}"
        # best-ref metadata from the page (og / twitter / meta)
        "var M=function(q){var el=document.querySelector(q);"
        "return el?el.getAttribute('content'):'';};"
        "var c={url:u,title:document.title,selection:s,source_page:sp,"
        "author:M(\"meta[name='author']\")||M(\"meta[property='article:author']\"),"
        "site_name:M(\"meta[property='og:site_name']\"),"
        "description:M(\"meta[property='og:description']\")||M(\"meta[name='description']\"),"
        "published:M(\"meta[property='article:published_time']\")||M(\"meta[name='date']\"),"
        "captured_at:Math.floor(Date.now()/1000)};"
        "var b=new Blob([JSON.stringify(c,null,2)],{type:'application/json'});"
        "var d=document.createElement('a');d.href=URL.createObjectURL(b);"
        "d.download='capture-'+Date.now()+'.chronos.json';"
        "document.body.appendChild(d);d.click();d.remove();"
        "})();"
    )
    return "javascript:" + js
