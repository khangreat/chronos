"""Reddit account-export parser.

Reddit's data export ships saved_posts.csv / saved_comments.csv, each with an
`id` and a `permalink` column. This turns those rows into normalized records
(url + platform id + kind), without needing a Reddit account or API. Pure
parsing — the service layer handles storage, packaging, and provenance.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import List, Optional

_BASE = "https://www.reddit.com"


@dataclass
class RedditRecord:
    url: str
    platform_id: str
    kind: str          # "post" | "comment"
    title: str


def _full_url(permalink: str) -> str:
    permalink = (permalink or "").strip()
    if not permalink:
        return ""
    if permalink.startswith("http"):
        return permalink
    return _BASE + ("" if permalink.startswith("/") else "/") + permalink


def _title_from(permalink: str, pid: str, kind: str) -> str:
    # reddit permalinks look like /r/sub/comments/xxxx/a_slug_title/
    parts = [p for p in (permalink or "").split("/") if p]
    slug = ""
    if "comments" in parts:
        i = parts.index("comments")
        if len(parts) > i + 2:
            slug = parts[i + 2].replace("_", " ")
    sub = parts[1] if len(parts) > 1 and parts[0] == "r" else ""
    label = slug.capitalize() if slug else f"Reddit {kind} {pid}"
    return f"{label}" + (f" — r/{sub}" if sub else "")


def parse_reddit_csv(text: str, kind: str = "post") -> List[RedditRecord]:
    out: List[RedditRecord] = []
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        row = { (k or "").strip().lower(): (v or "").strip()
                for k, v in raw.items() }
        permalink = row.get("permalink") or row.get("url") or ""
        pid = row.get("id") or ""
        url = _full_url(permalink)
        if not url:
            continue
        out.append(RedditRecord(
            url=url, platform_id=pid, kind=kind,
            title=_title_from(permalink, pid, kind)))
    return out


# --------------------------------------------------------------------------- #
# Whole export (v0.30): posts, comments, saved, upvoted — recognised by columns
# --------------------------------------------------------------------------- #
@dataclass
class RedditItem:
    role: str                 # post | comment | saved_post | saved_comment | upvoted
    url: str
    platform_id: str
    title: str
    text: str = ""
    subreddit: str = ""
    timestamp: Optional[int] = None
    link_url: str = ""        # a link post's target page
    thread_url: str = ""      # a comment's thread
    author: str = ""


def _ts(value: str) -> Optional[int]:
    """Reddit export dates look like '2023-05-01 12:34:56 UTC'."""
    from datetime import datetime, timezone
    v = (value or "").strip().replace(" UTC", "").replace("T", " ").rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(v, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return int(v) if v.isdigit() else None


def _rows(text: str):
    for raw in csv.DictReader(io.StringIO(text)):
        yield {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}


def _role_for(name: str, headers) -> Optional[str]:
    """Decide what a CSV holds from its name and columns. None = not archived."""
    h = set(headers)
    if name.startswith("saved_comment"):
        return "saved_comment"
    if name.startswith("saved_post") or name.startswith("saved"):
        return "saved_post"
    if any(w in name for w in ("downvote", "hidden", "ip_log", "message", "chat",
                               "account", "award", "moderat", "gild", "subscribed",
                               "subreddit", "friend", "block", "drafts", "poll")):
        return None
    if "upvote" in name or "vote" in name:
        return "upvoted"
    if "body" in h and ("title" in h or name.startswith("post")):
        return "post"
    if "body" in h and ({"link", "parent"} & h or name.startswith("comment")):
        return "comment"
    if {"id", "permalink"} <= h and len(h) <= 3:
        return "saved_post"
    return None


def _first_line(s: str, n: int = 80) -> str:
    s = " ".join((s or "").split())
    return s[:n] + ("…" if len(s) > n else "")


def parse_reddit_export(path, single_kind: Optional[str] = None) -> List[RedditItem]:
    """Read a whole Reddit export (zip, folder) or one CSV from it.
    `single_kind` ('post'/'comment') keeps the old meaning for a lone saved file."""
    from ._archive import basename, iter_files
    out: List[RedditItem] = []
    for rel, data in iter_files(path, lambda r: r.endswith(".csv")):
        name = basename(rel)
        text = data.decode("utf-8-sig", "replace")
        rows = list(_rows(text))
        if not rows:
            continue
        role = _role_for(name, rows[0].keys())
        if role is None:
            continue
        if single_kind and role in ("saved_post", "saved_comment"):
            role = "saved_comment" if single_kind == "comment" else "saved_post"
        for r in rows:
            url = _full_url(r.get("permalink") or "")
            if not url:
                continue
            if role == "upvoted" and r.get("direction", "up").lower() not in ("up", "1"):
                continue
            pid = r.get("id", "")
            sub = r.get("subreddit", "")
            if role == "post":
                body = r.get("body", "")
                link = r.get("url", "")
                if link and "reddit.com" in link:
                    link = ""                              # a text post, not a link
                out.append(RedditItem(
                    "post", url, pid, r.get("title") or _first_line(body) or
                    _title_from(url, pid, "post"), body, sub, _ts(r.get("date", "")),
                    link_url=link))
            elif role == "comment":
                body = r.get("body", "")
                out.append(RedditItem(
                    "comment", url, pid, _first_line(body) or
                    _title_from(url, pid, "comment"), body, sub, _ts(r.get("date", "")),
                    thread_url=_full_url(r.get("link", ""))))
            else:
                kind = "comment" if role == "saved_comment" else "post"
                out.append(RedditItem(role, url, pid, _title_from(
                    r.get("permalink", ""), pid, kind), subreddit=sub,
                    timestamp=_ts(r.get("date", ""))))
    return out
