"""SearchService — FTS5 does the work, not a Python loop.

Queries run against the bookmarks_fts virtual table and rank by bm25(). Falls
back to a safe LIKE query if a user's raw input isn't a valid FTS expression
(e.g. a stray quote), so search never throws on odd input.
"""

from __future__ import annotations

from typing import List

from ..core.models import Bookmark
from ..core.storage import Storage


def _fts_query(raw: str) -> str:
    """Turn free text into a prefix-AND FTS query, terms sanitised."""
    terms = [t for t in "".join(c if c.isalnum() else " " for c in raw).split() if t]
    return " AND ".join(f"{t}*" for t in terms)


class SearchService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def search(self, query: str, limit: int = 50) -> List[Bookmark]:
        query = (query or "").strip()
        if not query:
            return []
        fts = _fts_query(query)
        if fts:
            try:
                rows = self.storage.conn.execute(
                    """
                    SELECT b.* FROM bookmarks b
                    JOIN bookmarks_fts f ON f.rowid = b.id
                    WHERE bookmarks_fts MATCH ?
                    ORDER BY bm25(bookmarks_fts) LIMIT ?
                    """,
                    (fts, limit),
                ).fetchall()
                return self.storage._rows_to_bookmarks(rows)
            except Exception:
                pass  # fall through to LIKE
        like = f"%{query}%"
        rows = self.storage.conn.execute(
            """SELECT * FROM bookmarks
               WHERE title LIKE ? OR url LIKE ?
               ORDER BY date_added DESC LIMIT ?""",
            (like, like, limit),
        ).fetchall()
        return self.storage._rows_to_bookmarks(rows)
