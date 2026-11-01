"""Benchmark: old widget-per-row vs new model/view, with time + RSS.

Run offscreen. Builds custom row widgets the OLD way (as v0.3 did) for a modest
count, and loads a much larger set into the NEW model/view, to show the new
approach is both faster and flatter in memory despite far more data.
"""

import os
import resource
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)
from chronos.core.models import Bookmark  # noqa: E402
from chronos.gui.stream_panel import StreamPanel  # noqa: E402
from chronos.gui.theme.tokens import THEMES  # noqa: E402


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def bookmarks(n):
    return [Bookmark(id=i, url=f"https://example.test/path/{i}",
                     title=f"Bookmark item number {i} with a reasonably long title",
                     date_added=1_704_067_200 + i * 3600, browser="Firefox",
                     site_name="example.test", is_favorite=(i % 9 == 0))
            for i in range(n)]


def old_way(app, bms):
    """Recreate v0.3's approach: one custom QWidget per row."""
    lw = QListWidget()

    def make_row(b):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 7, 10, 7)
        t = QLabel(b.title); u = QLabel(b.url); m = QLabel(f"{b.dt:%d %b %Y} · {b.browser}")
        v.addWidget(t); v.addWidget(u); v.addWidget(m)
        return w

    t0 = time.perf_counter()
    for b in bms:
        it = QListWidgetItem(lw)
        row = make_row(b)
        it.setSizeHint(row.sizeHint())
        lw.setItemWidget(it, row)
    app.processEvents()
    dt = time.perf_counter() - t0
    widgets = len(lw.findChildren(QWidget))
    return dt, widgets


def new_way(bms):
    panel = StreamPanel(THEMES["dusk"])
    panel.resize(500, 700)
    t0 = time.perf_counter()
    panel.set_bookmarks(bms, "Bench")
    QApplication.instance().processEvents()
    dt = time.perf_counter() - t0
    widgets = len(panel.view.findChildren(QWidget))
    return dt, widgets


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])

    OLD_N = 5_000
    NEW_N = 50_000

    base = rss_mb()
    o_dt, o_widgets = old_way(app, bookmarks(OLD_N))
    after_old = rss_mb()

    n_dt, n_widgets = new_way(bookmarks(NEW_N))
    after_new = rss_mb()

    print(f"{'approach':<22}{'rows':>8}{'time(s)':>10}{'widgets':>10}{'RSS Δ MB':>12}")
    print("-" * 62)
    print(f"{'OLD widget-per-row':<22}{OLD_N:>8}{o_dt:>10.3f}{o_widgets:>10}"
          f"{after_old-base:>12.1f}")
    print(f"{'NEW model/view':<22}{NEW_N:>8}{n_dt:>10.3f}{n_widgets:>10}"
          f"{after_new-after_old:>12.1f}")
    print("-" * 62)
    print(f"NEW handled {NEW_N//OLD_N}x the rows; "
          f"per-row time old={o_dt/OLD_N*1e6:.1f}us  new={n_dt/NEW_N*1e6:.1f}us")
