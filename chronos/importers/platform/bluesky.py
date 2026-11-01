"""Bluesky export parser.

Handles the two common JSON shapes people can save without special tooling:
a `com.atproto.repo.listRecords` response (`{"records":[{uri,value:{text,
createdAt,reply}}]}`) and an `app.bsky.feed.getAuthorFeed` response
(`{"feed":[{post:{uri,author,record:{text,createdAt,reply}}}]}`). at:// URIs are
turned into bsky.app URLs, and replies carry the parent URI for threading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from ._social import iso_ts


@dataclass
class BlueskyPost:
    url: str
    at_uri: str
    text: str
    created_ts: Optional[int]
    reply_parent_uri: Optional[str]
    author: Optional[str]
    shared_url: Optional[str] = None


def at_to_url(at_uri: Optional[str], handle: Optional[str] = None) -> str:
    if not at_uri:
        return ""
    parts = at_uri.split("/")
    # at://<repo-did>/app.bsky.feed.post/<rkey>
    if len(parts) >= 5 and parts[3] == "app.bsky.feed.post":
        repo = handle or parts[2]
        return f"https://bsky.app/profile/{repo}/post/{parts[4]}"
    return at_uri


def _reply_parent(rec: dict) -> Optional[str]:
    return ((rec.get("reply") or {}).get("parent") or {}).get("uri")


def parse_bluesky(text: str) -> List[BlueskyPost]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out: List[BlueskyPost] = []
    if isinstance(data, dict) and "records" in data:
        for r in data["records"]:
            v = r.get("value", {}) if isinstance(r, dict) else {}
            uri = r.get("uri")
            if not uri:
                continue
            out.append(BlueskyPost(
                url=at_to_url(uri), at_uri=uri, text=v.get("text", ""),
                created_ts=iso_ts(v.get("createdAt")),
                reply_parent_uri=_reply_parent(v), author=None))
    elif isinstance(data, dict) and "feed" in data:
        for it in data["feed"]:
            post = it.get("post", {}) if isinstance(it, dict) else {}
            rec = post.get("record", {})
            uri = post.get("uri")
            if not uri:
                continue
            handle = (post.get("author") or {}).get("handle")
            out.append(BlueskyPost(
                url=at_to_url(uri, handle), at_uri=uri, text=rec.get("text", ""),
                created_ts=iso_ts(rec.get("createdAt")),
                reply_parent_uri=_reply_parent(rec), author=handle))
    return out


def parse_bluesky_car(data: bytes):
    """Bluesky's own "Export my data" file (.car). Returns (posts, liked_urls)."""
    from .atproto_car import read_repo
    did, records = read_repo(data)
    posts, likes = [], []
    for key, rec in sorted(records.items()):
        coll, _, rkey = key.partition("/")
        if coll == "app.bsky.feed.post":
            uri = f"at://{did}/{key}"
            embed = rec.get("embed") or {}
            ext = embed.get("external") if isinstance(embed, dict) else None
            posts.append(BlueskyPost(
                url=at_to_url(uri), at_uri=uri, text=rec.get("text", "") or "",
                created_ts=iso_ts(rec.get("createdAt")),
                reply_parent_uri=_reply_parent(rec), author=None,
                shared_url=(ext or {}).get("uri") if isinstance(ext, dict) else None))
        elif coll == "app.bsky.feed.like":
            subj = (rec.get("subject") or {}).get("uri")
            if subj:
                likes.append(at_to_url(subj))
    return posts, likes
