"""StatsService — timeline and aggregate views, computed by SQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..core.storage import Storage


@dataclass
class Stats:
    total: int
    by_year: List[Tuple[int, int]]
    by_browser: List[Tuple[str, int]]


class StatsService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def stats(self) -> Stats:
        return Stats(
            total=self.storage.count(),
            by_year=self.storage.year_counts(),
            by_browser=self.storage.browser_counts(),
        )

    def timeline(self) -> Dict[int, List[Tuple[int, int]]]:
        """year -> [(month, count), ...] ascending, for a timeline view."""
        rows = self.storage.conn.execute(
            """SELECT year, month, COUNT(*) c FROM bookmarks
               GROUP BY year, month ORDER BY year DESC, month ASC"""
        ).fetchall()
        out: Dict[int, List[Tuple[int, int]]] = {}
        for r in rows:
            out.setdefault(int(r["year"]), []).append((int(r["month"]), int(r["c"])))
        return out
