"""ProvenanceService — record how resources entered Chronos, and manage the
account-export data packages they came from.

A resource can have several acquisitions: seen in a browser bookmark, then in a
Reddit export, then captured live. Each acquisition is recorded once per
(method, source, package). This is what lets Chronos answer "everything I
deliberately saved on Reddit" or "how my relationship with this item evolved".
"""

from __future__ import annotations

import json
from typing import List, Optional

METHODS = {
    "browser_bookmark", "browser_history", "feed_discovered", "manual_capture",
    "platform_saved", "platform_liked", "imported", "received_from_bridge",
}


class ProvenanceService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- acquisitions ------------------------------------------------------- #
    def record(self, bookmark_id: int, method: str, source: Optional[str] = None,
               acquired_at: Optional[int] = None, package_id: Optional[int] = None,
               detail: Optional[dict] = None) -> Optional[int]:
        """Record an acquisition, idempotent per (bookmark, method, source,
        package). Returns the new id, or None if it already existed."""
        if method not in METHODS:
            raise ValueError(f"Unknown acquisition method: {method}")
        if self.ctx.storage.acquisition_exists(bookmark_id, method, source,
                                               package_id):
            return None
        return self.ctx.storage.add_acquisition(
            bookmark_id, method, source, acquired_at, package_id,
            json.dumps(detail, ensure_ascii=False) if detail else None)

    def record_for_urls(self, urls, method: str, source=None, package_id=None,
                        detail_by_url=None) -> int:
        """Record an acquisition for each URL that resolves to a bookmark."""
        n = 0
        for url in urls:
            bm = self.ctx.storage.get_by_url(url)
            if bm is None:
                continue
            d = (detail_by_url or {}).get(url)
            if self.record(bm.id, method, source, package_id=package_id, detail=d):
                n += 1
        return n

    def for_bookmark(self, bookmark_id: int) -> List[dict]:
        return self.ctx.storage.acquisitions_for(bookmark_id)

    def by_method(self, method: str, limit: int = 500) -> List:
        return self.ctx.storage.bookmarks_by_acquisition(method=method, limit=limit)

    def by_source(self, source: str, limit: int = 500) -> List:
        return self.ctx.storage.bookmarks_by_acquisition(source=source, limit=limit)

    # -- data packages ------------------------------------------------------ #
    def register_package(self, provider: str, **kw) -> tuple:
        """Register a data package. Returns (package_id, already_seen). If a
        package with the same archive_hash exists, it's reused (incremental
        re-import doesn't duplicate)."""
        h = kw.get("archive_hash")
        existing = self.ctx.storage.package_by_hash(h) if h else None
        if existing:
            return existing["id"], True
        return self.ctx.storage.add_package(provider, **kw), False

    def packages(self) -> List[dict]:
        return self.ctx.storage.all_packages()
