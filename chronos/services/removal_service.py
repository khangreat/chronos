"""RemovalService — delete bookmarks and their derived data safely.

Deleting a bookmark cascades its rows (tags, snippets, archive row) via foreign
keys, but the archive *file* on disk is derived data the cascade can't reach —
so we remove the file first, then the row. The core (schema, other bookmarks,
search index) always survives a removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class RemovalResult:
    removed: int
    files_deleted: int
    orphans_purged: int


class RemovalService:
    def __init__(self, ctx):
        self.ctx = ctx

    def remove_bookmark(self, bookmark_id: int) -> bool:
        had_file = self.ctx.archive.remove(bookmark_id)   # delete gz file + row
        self.ctx.storage.delete_bookmark(bookmark_id)      # cascades remaining rows
        return had_file

    def remove_many(self, ids: Iterable[int]) -> RemovalResult:
        removed = files = 0
        for bid in list(ids):
            if self.ctx.storage.get(bid) is None:
                continue
            if self.remove_bookmark(bid):
                files += 1
            removed += 1
        purged = self.ctx.archive.purge_orphans()
        return RemovalResult(removed=removed, files_deleted=files,
                             orphans_purged=purged)

    def purge_orphans(self) -> int:
        return self.ctx.archive.purge_orphans()
