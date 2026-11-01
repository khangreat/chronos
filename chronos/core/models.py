"""Domain models. Plain dataclasses — no DB, no Qt, no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class Bookmark:
    url: str
    title: str
    # Canonical timestamp: UNIX seconds (UTC). Importers normalise to this,
    # regardless of each browser's native epoch.
    date_added: int
    browser: str = "Firefox"
    folder_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    is_favorite: bool = False
    notes: str = ""
    page_text: Optional[str] = None
    is_dead: bool = False
    wayback_url: Optional[str] = None
    id: Optional[int] = None
    # Extracted-page / citation metadata (populated by the reader pipeline).
    page_title: Optional[str] = None
    byline: Optional[str] = None
    site_name: Optional[str] = None
    published_ts: Optional[int] = None
    excerpt: Optional[str] = None
    fetched_at: Optional[int] = None
    kind: str = "webpage"  # webpage, article, feed_entry, social_post, social_comment…

    @property
    def has_content(self) -> bool:
        return bool(self.fetched_at)

    @property
    def year(self) -> int:
        return datetime.fromtimestamp(self.date_added, tz=timezone.utc).year

    @property
    def month(self) -> int:
        return datetime.fromtimestamp(self.date_added, tz=timezone.utc).month

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.date_added, tz=timezone.utc)


@dataclass
class Snippet:
    """A captured quotation from a source bookmark — the unit Nawishtar cites.

    `quote` is the passage; `locator` is an optional human locator (e.g. a
    section or paragraph) carried into the citation; `note` is the user's own
    annotation. The source's full metadata lives on the referenced bookmark.
    """
    bookmark_id: int
    quote: str
    note: str = ""
    locator: Optional[str] = None
    created_at: Optional[int] = None
    id: Optional[int] = None
