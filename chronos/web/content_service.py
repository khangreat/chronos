"""ContentService — reader pipeline over Storage + PageFetcher.

Two entry points:
  - fetch_and_store(): touches the network (gated) then persists.
  - store_extracted(): persists content you already have (no network) — used by
    the HTML-import path and by tests, keeping the network out of the unit under
    test.
"""

from __future__ import annotations

import time
from typing import Optional

from ..core.storage import Storage
from ..net.policy import NetworkPolicy
from .extract import ExtractedPage
from .fetcher import PageFetcher


class ContentService:
    def __init__(self, storage: Storage, policy: NetworkPolicy):
        self.storage = storage
        self.policy = policy
        self.fetcher = PageFetcher(policy)

    def store_extracted(self, bookmark_id: int, page: ExtractedPage,
                        fetched_at: Optional[int] = None) -> None:
        self.storage.update_content(
            bookmark_id, page, fetched_at or int(time.time())
        )

    def fetch_and_store(self, bookmark_id: int) -> ExtractedPage:
        bm = self.storage.get(bookmark_id)
        if bm is None:
            raise ValueError(f"No bookmark id={bookmark_id}")
        page = self.fetcher.fetch(bm.url)   # gated: raises if network off
        self.store_extracted(bookmark_id, page)
        return page
