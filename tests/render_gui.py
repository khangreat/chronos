"""Render the GUI offscreen against seeded data and save screenshots.

Proves at artifact level that the window constructs, panels populate, selecting
a bookmark drives the reader, and the theme applies — then writes PNGs so the
design can actually be looked at. Runs with QT_QPA_PLATFORM=offscreen.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.web.extract import extract_content  # noqa: E402
from chronos.gui.theme.tokens import THEMES, build_qss  # noqa: E402
from chronos.gui.main_window import MainWindow  # noqa: E402
from tests.fixtures import (  # noqa: E402
    build_firefox_places, build_chromium_bookmarks, build_netscape_html,
)

ARTICLE = """<html><head><title>Understanding FTS5 — SQLite</title>
<meta property="og:site_name" content="SQLite Docs">
<meta name="author" content="Jane Roe">
<meta property="article:published_time" content="2024-05-01T09:00:00Z"></head>
<body><article><h1>Understanding FTS5</h1>
<p>FTS5 is an SQLite extension providing full-text search over documents.</p>
<p>It ranks matches with the bm25 algorithm, which balances term frequency
against how common a term is across the whole collection.</p>
<p>Chronos uses it so search is done by the database, not a Python loop.</p>
</article></body></html>"""


def seed(ctx):
    d = Path(tempfile.mkdtemp())
    build_firefox_places(d / "places.sqlite")
    build_chromium_bookmarks(d / "Bookmarks")
    build_netscape_html(d / "bm.html")
    ctx.bookmarks.import_from("firefox", d / "places.sqlite")
    ctx.bookmarks.import_from("chrome", d / "Bookmarks")
    ctx.bookmarks.import_html(d / "bm.html")
    # give one bookmark real fetched content + a favorite
    bm = ctx.storage.get_by_url("https://docs.python.org")
    ctx.storage.set_favorite(bm.id, True)
    fts = ctx.storage.find_by_url_pattern("%sqlite.org/fts5%")
    if fts:
        ctx.content.store_extracted(
            fts[0].id, extract_content(ARTICLE, "https://sqlite.org/fts5.html"))


def render(theme_name: str, out: Path) -> None:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_qss(THEMES[theme_name]))
    ctx = ApplicationContext.for_dir(Path(tempfile.mkdtemp()) / "home")
    seed(ctx)
    win = MainWindow(ctx)
    win.resize(1180, 760)
    win.show()

    # verify population
    assert win.stream.count() > 0, "stream did not populate"
    # drive a selection -> reader
    fts = ctx.storage.find_by_url_pattern("%sqlite.org/fts5%")[0]
    win._show_bookmark(fts.id)
    assert "FTS5" in win.reader.title.text(), "reader title not set"
    assert win.reader.body.toPlainText().strip(), "reader body empty"
    # run a search
    win.search.setText("python")
    win._run_search()
    assert win.stream.count() > 0, "search produced nothing"
    # reset to timeline view for the screenshot
    win.search.clear()
    win._show_bookmark(fts.id)

    app.processEvents()
    time.sleep(0.15)
    app.processEvents()
    pix = win.grab()
    pix.save(str(out))
    print(f"[{theme_name}] stream items={win.stream.count()} "
          f"reader_ok=True saved={out.name} ({out.stat().st_size} bytes)"
          if out.exists() else f"[{theme_name}] SAVE FAILED")
    ctx.close()


if __name__ == "__main__":
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    render("dusk", outdir / "chronos_dusk.png")
    render("midnight", outdir / "chronos_midnight.png")
    print("OK")
