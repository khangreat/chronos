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


def overview(ctx) -> dict:
    """Everything the Overview tab shows, computed in a few queries."""
    from .describe import _src
    st = ctx.storage
    c = st.conn
    one = lambda sql: c.execute(sql).fetchone()[0] or 0          # noqa: E731
    items = st.count()
    months = c.execute(
        """SELECT year, month, COUNT(*) n FROM bookmarks WHERE year IS NOT NULL
           GROUP BY year, month ORDER BY year DESC, month DESC LIMIT 12""").fetchall()
    return {
        "items": items,
        "sites": one("SELECT COUNT(DISTINCT domain) FROM bookmarks WHERE domain IS NOT NULL "
                     "AND domain != ''"),
        "offline": one("SELECT COUNT(*) FROM archives"),
        "gone": one("SELECT COUNT(*) FROM bookmarks WHERE is_dead = 1"),
        "favourites": st.favorite_count(),
        "quotes": one("SELECT COUNT(*) FROM snippets"),
        "takeaways": one("SELECT COUNT(*) FROM takeaways"),
        "tags": one("SELECT COUNT(*) FROM tags"),
        "first": one("SELECT MIN(date_added) FROM bookmarks WHERE date_added > 0"),
        "by_year": [(str(y), n) for y, n in sorted(st.year_counts()) if y],
        "by_kind": list(st.kind_counts()),           # raw kinds; the window names them
        # where each item came from: recorded imports, else the label every item has
        "by_source": ([(_src(s), n) for s, n in st.source_counts()]
                      or [(b or "\u2014", n) for b, n in st.browser_counts()])[:10],
        "top_tags": [(r[0], r[1]) for r in c.execute(
            """SELECT t.name, COUNT(*) n FROM bookmark_tags bt JOIN tags t ON t.id = bt.tag_id
               GROUP BY t.id ORDER BY n DESC LIMIT 10""")],
        "last_months": [(f"{r['year']}-{r['month']:02d}", r["n"]) for r in reversed(months)],
    }
