"""RSS/Atom parsing.

Prefers `feedparser` (robust against the malformed feeds real sites ship). Falls
back to a compact stdlib ElementTree parser for RSS 2.0 and Atom so the feeds
feature works without the optional dependency. Pure function on feed text — the
(gated) network fetch lives in FeedService.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

try:
    import feedparser  # type: ignore
    _HAS_FEEDPARSER = True
except Exception:  # pragma: no cover
    _HAS_FEEDPARSER = False


@dataclass
class FeedEntry:
    url: str
    title: str
    published_ts: Optional[int] = None
    summary: Optional[str] = None


@dataclass
class FeedResult:
    title: str = ""
    site_url: Optional[str] = None
    entries: List[FeedEntry] = field(default_factory=list)
    parser: str = "stdlib"


def _to_ts(value) -> Optional[int]:
    if not value:
        return None
    if isinstance(value, str):
        # try RFC822 (RSS) then ISO (Atom)
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except (TypeError, ValueError):
            pass
        for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value.replace("Z", "+0000"), f)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
    return None


def parse_feed(text: str, feed_url: str = "") -> FeedResult:
    if _HAS_FEEDPARSER:
        return _parse_with_feedparser(text)
    return _parse_stdlib(text)


def _parse_with_feedparser(text: str) -> FeedResult:  # pragma: no cover - optional
    d = feedparser.parse(text)
    res = FeedResult(parser="feedparser")
    res.title = (d.feed.get("title") or "") if d.feed else ""
    res.site_url = d.feed.get("link") if d.feed else None
    for e in d.entries:
        ts = None
        if getattr(e, "published_parsed", None):
            ts = int(datetime(*e.published_parsed[:6], tzinfo=timezone.utc).timestamp())
        elif getattr(e, "updated_parsed", None):
            ts = int(datetime(*e.updated_parsed[:6], tzinfo=timezone.utc).timestamp())
        link = e.get("link") or ""
        if link:
            res.entries.append(FeedEntry(
                url=link, title=e.get("title") or link,
                published_ts=ts, summary=e.get("summary")))
    return res


_ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_stdlib(text: str) -> FeedResult:
    res = FeedResult(parser="stdlib")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return res

    tag = root.tag.lower()
    if tag.endswith("rss") or root.find("channel") is not None:
        ch = root.find("channel")
        if ch is None:
            return res
        res.title = (ch.findtext("title") or "").strip()
        res.site_url = (ch.findtext("link") or "").strip() or None
        for item in ch.findall("item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            res.entries.append(FeedEntry(
                url=link,
                title=(item.findtext("title") or link).strip(),
                published_ts=_to_ts(item.findtext("pubDate")),
                summary=(item.findtext("description") or None),
            ))
    elif tag.endswith("feed"):  # Atom
        res.title = (root.findtext(f"{_ATOM}title") or "").strip()
        for ln in root.findall(f"{_ATOM}link"):
            if ln.get("rel") in (None, "alternate"):
                res.site_url = ln.get("href")
                break
        for entry in root.findall(f"{_ATOM}entry"):
            href = ""
            for ln in entry.findall(f"{_ATOM}link"):
                if ln.get("rel") in (None, "alternate"):
                    href = ln.get("href") or ""
                    break
            if not href:
                continue
            date = (entry.findtext(f"{_ATOM}published")
                    or entry.findtext(f"{_ATOM}updated"))
            res.entries.append(FeedEntry(
                url=href,
                title=(entry.findtext(f"{_ATOM}title") or href).strip(),
                published_ts=_to_ts(date),
                summary=(entry.findtext(f"{_ATOM}summary") or None),
            ))
    return res
