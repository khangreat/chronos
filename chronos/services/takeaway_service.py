"""TakeawayService — authored distillations.

A Takeaway is what you wanted to *retain* from a resource: your one-line point,
the reason it's worth keeping. It's distinct from a Quote (the source's exact
words) and from a Note (your extended thoughts). It's authored data, so it
survives dedupe/merge (reassigned to the survivor) and is only removed when you
remove it or delete the resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Takeaway:
    id: int
    bookmark_id: int
    text: str
    created_at: int


class TakeawayService:
    def __init__(self, ctx):
        self.ctx = ctx

    def add(self, bookmark_id: int, text: str) -> int:
        text = (text or "").strip()
        if not text:
            raise ValueError("Takeaway text is empty.")
        if self.ctx.storage.get(bookmark_id) is None:
            raise ValueError(f"No resource id={bookmark_id}")
        return self.ctx.storage.add_takeaway(bookmark_id, text)

    def for_bookmark(self, bookmark_id: int) -> List[Takeaway]:
        return [Takeaway(**r) for r in self.ctx.storage.takeaways_for(bookmark_id)]

    def all(self) -> List[Takeaway]:
        return [Takeaway(**r) for r in self.ctx.storage.all_takeaways()]

    def update(self, takeaway_id: int, text: str) -> None:
        text = (text or "").strip()
        if not text:
            raise ValueError("Takeaway text is empty.")
        self.ctx.storage.update_takeaway(takeaway_id, text)

    def remove(self, takeaway_id: int) -> None:
        self.ctx.storage.delete_takeaway(takeaway_id)
