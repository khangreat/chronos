"""Mastodon account-export parser.

A Mastodon export is an archive containing ActivityPub JSON: `outbox.json` (your
posts, as an OrderedCollection of Create activities wrapping Note objects),
plus `bookmarks.json` and `likes.json` (collections of status URLs). This
normalises those into records; the service layer stores them. Pure parsing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlsplit

from ._social import iso_ts, strip_html


@dataclass
class MastodonPost:
    url: str
    status_id: str
    text: str
    created_ts: Optional[int]
    in_reply_to: Optional[str]   # id/url of the status this replies to
    author: Optional[str]        # @user@domain


def _handle(attributed_to: Optional[str]) -> Optional[str]:
    if not attributed_to:
        return None
    parts = [p for p in urlsplit(attributed_to).path.split("/") if p]
    user = parts[-1] if parts else ""
    host = urlsplit(attributed_to).hostname or ""
    return f"@{user}@{host}" if user and host else None


def _items(data: dict) -> list:
    return data.get("orderedItems") or data.get("items") or []


def parse_outbox(text: str) -> List[MastodonPost]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out: List[MastodonPost] = []
    for it in _items(data):
        if not isinstance(it, dict) or it.get("type") != "Create":
            continue
        obj = it.get("object")
        if not isinstance(obj, dict) or obj.get("type") != "Note":
            continue
        url = obj.get("url") or obj.get("id")
        if not url:
            continue
        out.append(MastodonPost(
            url=url, status_id=obj.get("id") or url,
            text=strip_html(obj.get("content")),
            created_ts=iso_ts(obj.get("published") or it.get("published")),
            in_reply_to=obj.get("inReplyTo"),
            author=_handle(obj.get("attributedTo"))))
    return out


def parse_collection_urls(text: str) -> List[str]:
    """bookmarks.json / likes.json — a collection of status URLs (strings)."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return [x for x in _items(data) if isinstance(x, str)]
