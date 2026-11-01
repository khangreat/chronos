"""LinkService — check whether bookmarked pages are still alive, and fall back
to a Wayback snapshot for dead ones. All network access is gated (link_check for
the HEAD probe, wayback for the archive lookup); nothing runs while offline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from ..core.storage import Storage
from ..net.policy import NetworkPolicy
from .fetcher import PageFetcher


@dataclass
class CheckResult:
    checked: int
    dead: int
    archived: int


class LinkService:
    def __init__(self, storage: Storage, policy: NetworkPolicy):
        self.storage = storage
        self.policy = policy
        self.fetcher = PageFetcher(policy)

    def check_one(self, bookmark_id: int, use_wayback: bool = True) -> bool:
        """Probe one link; mark status; look up an archive if dead. Returns
        True if alive. Raises NetworkDisabled if link_check is off."""
        bm = self.storage.get(bookmark_id)
        if bm is None:
            raise ValueError(f"No bookmark id={bookmark_id}")
        alive, _code = self.fetcher.check_alive(bm.url)
        self.storage.mark_link_status(bookmark_id, not alive, int(time.time()))
        if not alive and use_wayback and self.policy.is_allowed("wayback"):
            snap = self.fetcher.wayback_url(bm.url)
            if snap:
                self.storage.set_wayback(bookmark_id, snap)
        return alive

    def check_bookmarks(self, bookmarks: List, use_wayback: bool = True) -> CheckResult:
        checked = dead = archived = 0
        for b in bookmarks:
            try:
                alive = self.check_one(b.id, use_wayback=use_wayback)
            except Exception:
                continue
            checked += 1
            if not alive:
                dead += 1
                if self.storage.get(b.id).wayback_url:
                    archived += 1
        return CheckResult(checked, dead, archived)

    def check_all(self, limit: int = 0, use_wayback: bool = True) -> CheckResult:
        return self.check_bookmarks(self.storage.all_bookmarks(limit),
                                    use_wayback=use_wayback)
