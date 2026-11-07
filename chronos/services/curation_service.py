"""CurationService — find and merge duplicate bookmarks.

Duplicates are bookmarks whose URLs normalise to the same thing (host lowercased,
fragment dropped, trailing slash trimmed) — typically the same page saved in more
than one browser. Merging keeps one canonical record and folds tags, favourite
state, notes, and captured snippets into it before removing the rest, so nothing
the user added is lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from urllib.parse import urlsplit, urlunsplit

from ..core.models import Bookmark
from ..core.storage import Storage


def normalize_url(url: str) -> str:
    from ..web.video import parse_video
    v = parse_video(url)
    if v is not None:                   # youtu.be/x, /shorts/x, watch?v=x … are one video
        return v.url
    try:
        s = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (s.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = s.path.rstrip("/") or "/"
    netloc = host + (f":{s.port}" if s.port else "")
    return urlunsplit((s.scheme.lower(), netloc, path, s.query, ""))


@dataclass
class MergeResult:
    groups: int
    removed: int


class CurationService:
    def __init__(self, storage: Storage, before_merge=None):
        self.storage = storage
        self.before_merge = before_merge      # e.g. a safety copy, before rewriting

    def find_duplicate_groups(self) -> List[List[Bookmark]]:
        buckets: Dict[str, List[Bookmark]] = {}
        for b in self.storage.all_bookmarks():
            buckets.setdefault(normalize_url(b.url), []).append(b)
        return [g for g in buckets.values() if len(g) > 1]

    def _canonical(self, group: List[Bookmark]) -> Bookmark:
        # Prefer a record with fetched content, else a favourite, else lowest id.
        return sorted(
            group,
            key=lambda b: (not b.has_content, not b.is_favorite, b.id or 0)
        )[0]

    def merge_group(self, group: List[Bookmark]) -> int:
        canon = self._canonical(group)
        others = [b for b in group if b.id != canon.id]

        tags = set(canon.tags)
        favorite = canon.is_favorite
        notes = [canon.notes] if canon.notes else []
        for o in others:
            tags.update(o.tags)
            favorite = favorite or o.is_favorite
            if o.notes and o.notes not in notes:
                notes.append(o.notes)
            self.storage.reassign_snippets(o.id, canon.id)
            self.storage.reassign_takeaways(o.id, canon.id)

        if tags != set(canon.tags):
            self.storage.set_tags(canon.id, sorted(tags))
        if favorite != canon.is_favorite:
            self.storage.set_favorite(canon.id, favorite)
        merged_notes = "\n".join(notes)
        if merged_notes != canon.notes:
            self.storage.update_notes(canon.id, merged_notes)

        for o in others:
            self.storage.delete_bookmark(o.id)
        return len(others)

    def merge_all(self) -> MergeResult:
        groups = self.find_duplicate_groups()
        if groups and self.before_merge:
            self.before_merge()                              # merging rewrites items
        removed = sum(self.merge_group(g) for g in groups)
        return MergeResult(groups=len(groups), removed=removed)
