"""FeedService — subscribe to feeds and pull their entries into the store.

Feed entries are stored as bookmarks with browser="RSS" and the feed's title as
the folder, so everything downstream (timeline, search, reader, interop/CSL-JSON
citations) works on feed items with no special-casing. Fetching is gated by the
'feeds' network capability; parsing is a pure function and needs no network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional
from urllib.request import Request, urlopen

from ..core.models import Bookmark
from ..core.storage import Storage
from ..net.policy import NetworkPolicy
from .parse import FeedResult, parse_feed

_UA = "ChronosArchive/0.6 (+local; feeds)"


@dataclass
class RefreshResult:
    feed_id: int
    title: str
    found: int
    new: int
    parser: str


class FeedService:
    def __init__(self, storage: Storage, policy: NetworkPolicy, timeout: int = 15):
        self.storage = storage
        self.policy = policy
        self.timeout = timeout

    def _fetch(self, url: str) -> str:
        self.policy.require("feeds")  # gated: raises if feeds capability is off
        req = Request(url, headers={"User-Agent": _UA})
        with urlopen(req, timeout=self.timeout) as r:
            cs = r.headers.get_content_charset() or "utf-8"
            return r.read().decode(cs, errors="replace")

    def subscribe(self, feed_url: str) -> RefreshResult:
        """Fetch a feed, register it, and import its current entries."""
        text = self._fetch(feed_url)
        parsed = parse_feed(text, feed_url)
        fid = self.storage.add_feed(feed_url, parsed.title, parsed.site_url)
        return self._store_entries(fid, parsed)

    def subscribe_from_text(self, feed_url: str, text: str) -> RefreshResult:
        """Register + import from already-fetched feed text (no network)."""
        parsed = parse_feed(text, feed_url)
        fid = self.storage.add_feed(feed_url, parsed.title, parsed.site_url)
        return self._store_entries(fid, parsed)

    def refresh(self, feed_id: int, feed_url: str) -> RefreshResult:
        text = self._fetch(feed_url)
        parsed = parse_feed(text, feed_url)
        return self._store_entries(feed_id, parsed)

    def refresh_all(self) -> List[RefreshResult]:
        out: List[RefreshResult] = []
        for f in self.storage.list_feeds():
            try:
                out.append(self.refresh(f["id"], f["url"]))
            except Exception:
                continue  # one bad feed must not abort the sweep
        return out

    def _store_entries(self, feed_id: int, parsed: FeedResult) -> RefreshResult:
        now = int(time.time())
        bms = []
        for e in parsed.entries:
            bms.append(Bookmark(
                url=e.url,
                title=e.title,
                date_added=e.published_ts or now,
                published_ts=e.published_ts,
                browser="RSS",
                folder_name=parsed.title or None,
                site_name=parsed.site_url,
                excerpt=(e.summary[:280] if e.summary else None),
                kind="feed_entry",
            ))
        new = self.storage.import_bookmarks(bms)
        # provenance: each feed item is 'feed_discovered' from this feed
        for e in parsed.entries:
            row = self.storage.get_by_url(e.url)
            if row is not None and not self.storage.acquisition_exists(
                    row.id, "feed_discovered", parsed.title or "rss", None):
                self.storage.add_acquisition(
                    row.id, "feed_discovered", parsed.title or "rss",
                    acquired_at=e.published_ts)
        self.storage.touch_feed(feed_id, now)
        return RefreshResult(feed_id, parsed.title, len(bms), new, parsed.parser)
