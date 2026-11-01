"""Reddit's own JSON — what reddit.com returns for /user/NAME/saved.json,
/upvoted.json, /submitted.json, /comments.json, /api/info.json and /by_id/.

It arrives two ways: from the Chronos browser extension, which reads your
saved, upvoted, posts and comments while you're logged in to reddit.com (and
fills in the titles and text that Reddit's data download leaves out), or as
.json files you saved from those addresses yourself. Either way it becomes the
same RedditItem records the data-download importer makes.
"""

from __future__ import annotations

from html import unescape
from typing import Iterable, List

from .reddit import RedditItem, _first_line

_BASE = "https://www.reddit.com"


def _children(data) -> Iterable[dict]:
    if isinstance(data, list):                       # a list of listings, or of things
        for d in data:
            yield from _children(d)
        return
    if not isinstance(data, dict):
        return
    if data.get("kind") == "Listing":
        yield from (data.get("data") or {}).get("children") or []
    elif data.get("kind") in ("t1", "t3"):
        yield data


def parse_listing(data, role: str = "") -> List[RedditItem]:
    """Listing JSON → items. `role` (saved/upvoted/submitted/comments/fill)
    says what the list was; without it, posts and comments are your saves."""
    out: List[RedditItem] = []
    for ch in _children(data):
        kind, d = ch.get("kind"), ch.get("data") or {}
        if not isinstance(d, dict):
            continue
        link = d.get("permalink") or ""
        url = _BASE + link if link.startswith("/") else link
        if not url:
            continue
        sub = d.get("subreddit") or ""
        ts = int(d["created_utc"]) if d.get("created_utc") else None
        author = d.get("author") or ""
        if kind == "t3":
            text = unescape(d.get("selftext") or "")
            target = d.get("url_overridden_by_dest") or d.get("url") or ""
            if "reddit.com" in target or target.startswith("/"):
                target = ""
            r = {"saved": "saved_post", "upvoted": "upvoted", "submitted": "post",
                 "comments": "post"}.get(role, "fill_post" if role == "fill" else "saved_post")
            out.append(RedditItem(r, url, d.get("id") or "", unescape(d.get("title") or "")
                                  or _first_line(text), text, sub, ts, link_url=target))
        else:
            text = unescape(d.get("body") or "")
            r = {"saved": "saved_comment", "upvoted": "upvoted", "comments": "comment",
                 "submitted": "comment"}.get(role, "fill_comment" if role == "fill" else "saved_comment")
            thread = d.get("link_permalink") or ""
            if not thread and d.get("link_id") and sub:
                thread = f"{_BASE}/r/{sub}/comments/{d['link_id'].split('_', 1)[-1]}/"
            out.append(RedditItem(r, url, d.get("id") or "", _first_line(text) or
                                  unescape(d.get("link_title") or ""), text, sub, ts,
                                  thread_url=thread))
        out[-1].author = author
    return out
