"""ResourceService — resource kinds and the relationship graph.

This is the first step of evolving `Bookmark` toward the richer `Resource` model
from the archive vision: a resource has a `kind`, and resources relate to each
other (a comment replies_to a post, a post quotes another, items belong in a
thread). Additive — no rename, no rewrite.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..core.models import Bookmark

KINDS = {
    "webpage", "article", "feed_entry", "social_post", "social_comment",
    "thread", "image", "place", "product", "generic", "video", "search",
}
RELS = {"reply_to", "quotes", "in_thread", "related", "links_to", "embeds"}


class ResourceService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- kind --------------------------------------------------------------- #
    def set_kind(self, bookmark_id: int, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"Unknown resource kind: {kind}")
        self.ctx.storage.set_kind(bookmark_id, kind)

    def by_kind(self, kind: str, limit: int = 500) -> List[Bookmark]:
        return self.ctx.storage.bookmarks_by_kind(kind, limit)

    # -- relationships ------------------------------------------------------ #
    def relate(self, src_id: int, dst_id: int, rel: str) -> None:
        if rel not in RELS:
            raise ValueError(f"Unknown relationship: {rel}")
        if src_id == dst_id:
            raise ValueError("A resource cannot relate to itself.")
        self.ctx.storage.add_relationship(src_id, dst_id, rel)

    def unrelate(self, src_id: int, dst_id: int, rel: str) -> None:
        self.ctx.storage.remove_relationship(src_id, dst_id, rel)

    def outgoing(self, bookmark_id: int, rel=None) -> List[Tuple[str, Bookmark]]:
        return self.ctx.storage.relationships_out(bookmark_id, rel)

    def incoming(self, bookmark_id: int, rel=None) -> List[Tuple[str, Bookmark]]:
        return self.ctx.storage.relationships_in(bookmark_id, rel)

    # -- convenience for social structure ----------------------------------- #
    def parent(self, bookmark_id: int) -> Optional[Bookmark]:
        """The resource this one replies_to (e.g. a comment's submission)."""
        out = self.ctx.storage.relationships_out(bookmark_id, "reply_to")
        return out[0][1] if out else None

    def replies(self, bookmark_id: int) -> List[Bookmark]:
        """Resources that reply_to this one (e.g. a post's saved comments)."""
        return [b for _, b in
                self.ctx.storage.relationships_in(bookmark_id, "reply_to")]

    def thread_members(self, thread_id: int) -> List[Bookmark]:
        return [b for _, b in
                self.ctx.storage.relationships_in(thread_id, "in_thread")]
