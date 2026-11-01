"""SnippetService — capture quotations from a source bookmark.

A snippet is created from selected text (in the reader, or passed directly). The
service trims and validates the quote; everything citation-related is derived
from the source bookmark via interop when needed.
"""

from __future__ import annotations

from typing import List, Optional

from ..core.models import Snippet
from ..core.storage import Storage


class SnippetService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def capture(self, bookmark_id: int, quote: str, note: str = "",
                locator: Optional[str] = None) -> Snippet:
        quote = (quote or "").strip()
        if not quote:
            raise ValueError("Cannot capture an empty quote.")
        if self.storage.get(bookmark_id) is None:
            raise ValueError(f"No source bookmark id={bookmark_id}")
        snip = Snippet(bookmark_id=bookmark_id, quote=quote,
                       note=note.strip(), locator=locator)
        snip.id = self.storage.add_snippet(snip)
        return snip

    def for_bookmark(self, bookmark_id: int) -> List[Snippet]:
        return self.storage.snippets_for(bookmark_id)

    def all(self) -> List[Snippet]:
        return self.storage.all_snippets()

    def delete(self, snippet_id: int) -> None:
        self.storage.delete_snippet(snippet_id)
