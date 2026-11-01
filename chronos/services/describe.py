"""Plain-language descriptions of archive items, shared by the reader, the
stream, screen-reader text and AI context packs (no Qt here)."""

from __future__ import annotations

from typing import List

from ..core.models import Bookmark

_KIND_WORD = {
    "social_post": "Post", "social_comment": "Comment", "thread": "Thread",
    "article": "Article", "feed_entry": "Feed item", "image": "Image",
    "place": "Place", "product": "Product", "webpage": "Page", "generic": "Item",
    "video": "Video",
}


def byline_for(bm: Bookmark) -> str:
    """'Post by @x on m.social, 10 March 2026' — one plain sentence."""
    s = _KIND_WORD.get(getattr(bm, "kind", "webpage"), "Page")
    if bm.byline:
        s += f" by {bm.byline}"
    if bm.site_name:
        s += f" {'in' if s.startswith('Article') else 'on'} {bm.site_name}"
    return f"{s}, {bm.dt.day} {bm.dt:%B %Y}" if hasattr(bm, "dt") else s


_SOURCE_NAMES = {
    "firefox": "Firefox", "chrome": "Chrome", "chromium": "Chromium",
    "edge": "Edge", "brave": "Brave", "vivaldi": "Vivaldi", "opera": "Opera",
    "reddit": "Reddit", "x": "X", "mastodon": "Mastodon", "bluesky": "Bluesky",
    "facebook": "Facebook", "html": "an HTML export",
    "google_takeout": "Google Takeout", "html": "an HTML export", "rss": "a feed",
    "reader": "the reader",
}


def _src(name) -> str:
    if not name:
        return ""
    return _SOURCE_NAMES.get(str(name).lower(), str(name))


def provenance_sentences(acquisitions) -> List[str]:
    """Turn acquisition records into short plain sentences, oldest first."""
    import datetime as _dt
    out = []
    for a in sorted(acquisitions, key=lambda r: r.get("acquired_at") or 0):
        m, src = a.get("method"), _src(a.get("source"))
        phrase = {
            "browser_bookmark": f"Bookmarked in {src or 'a browser'}",
            "browser_history": f"Visited in {src or 'a browser'}",
            "feed_discovered": f"Arrived through {src or 'a feed'}",
            "manual_capture": (f"Captured from {src}" if src and src != "the reader"
                               else "Captured while reading"),
            "platform_saved": f"Saved on {src or 'a platform'}",
            "platform_liked": f"Liked on {src or 'a platform'}",
            "imported": f"Imported from {src or 'an export'}",
            "received_from_bridge": f"Sent from {src or 'another app'}",
        }.get(m, "Added")
        ts = a.get("acquired_at")
        if ts:
            d = _dt.datetime.fromtimestamp(int(ts))
            phrase += f", {d.day} {d:%b %Y}"
        if phrase not in out:
            out.append(phrase)
    return out
