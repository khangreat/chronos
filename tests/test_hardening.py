"""v0.4 tests: threading correctness, N+1 elimination, SQL month/pagination,
reader HTML escaping, and history import.
"""

from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.config import Config, Settings  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.web.extract import extract_content  # noqa: E402
from tests.fixtures import (  # noqa: E402
    build_firefox_history, build_chromium_history,
)

try:
    from PySide6.QtCore import QEventLoop
    _HAS_QT = True
except Exception:
    _HAS_QT = False


class HistoryImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_hist_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_firefox_history_dedupes_to_latest_visit(self):
        fx = self.tmp / "places.sqlite"
        build_firefox_history(fx)
        r = self.ctx.bookmarks.import_from("firefox history", fx)
        self.assertEqual(r.found, 2)   # one row per url despite 2 visits each
        bm = self.ctx.storage.get_by_url("https://news.example.com/a")
        self.assertEqual(bm.browser, "Firefox history")
        self.assertEqual((bm.year, bm.month), (2024, 2))

    def test_chromium_history_epoch(self):
        h = self.tmp / "History"
        build_chromium_history(h)
        r = self.ctx.bookmarks.import_from("chrome history", h)
        self.assertEqual(r.found, 2)
        bm = self.ctx.storage.get_by_url("https://docs.rs/tokio")
        self.assertEqual(bm.year, 2024)  # not 1601

    def test_history_and_bookmarks_coexist_without_collision(self):
        from tests.fixtures import build_firefox_places
        bm_db = self.tmp / "places.sqlite"
        hist_db = self.tmp / "hist.sqlite"
        build_firefox_places(bm_db)
        build_firefox_history(hist_db)
        self.ctx.bookmarks.import_from("firefox", bm_db)
        self.ctx.bookmarks.import_from("firefox history", hist_db)
        browsers = dict(self.ctx.stats.stats().by_browser)
        self.assertEqual(browsers.get("Firefox"), 3)
        self.assertEqual(browsers.get("Firefox history"), 2)


class PerformanceCorrectnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_perf_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        # 60 bookmarks within one year (Jan 2024), each with two tags.
        for i in range(60):
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://ex.test/{i}", title=f"Item {i}",
                date_added=1_704_067_200 + i * 3600,
                browser="Firefox"))
            self.ctx.storage.set_tags(bid, ["alpha", f"n{i%3}"], commit=False)
        self.ctx.storage.conn.commit()

    def tearDown(self):
        self.ctx.close()

    def test_no_n_plus_one_on_bulk_load(self):
        # Count SELECTs against bookmark_tags while loading a page of rows.
        counter = {"n": 0}

        def trace(sql):
            if "bookmark_tags" in sql:
                counter["n"] += 1

        self.ctx.storage.conn.set_trace_callback(trace)
        rows = self.ctx.storage.by_period(
            self.ctx.storage.year_counts()[0][0], limit=500)
        self.ctx.storage.conn.set_trace_callback(None)
        self.assertGreaterEqual(len(rows), 50)
        # Bulk loader must issue at most a couple of tag queries, not one per row.
        self.assertLessEqual(counter["n"], 2, f"N+1 detected: {counter['n']} tag queries")
        self.assertTrue(all("alpha" in b.tags for b in rows))

    def test_by_period_month_filter_in_sql(self):
        year = self.ctx.storage.year_counts()[0][0]
        # month filter returns only that month, and fewer than the whole year
        whole = self.ctx.storage.count_period(year)
        jan = self.ctx.storage.by_period(year, month=1)
        self.assertTrue(all(b.month == 1 for b in jan))
        self.assertLessEqual(len(jan), whole)

    def test_by_period_pagination(self):
        year = self.ctx.storage.year_counts()[0][0]
        page1 = self.ctx.storage.by_period(year, limit=10, offset=0)
        page2 = self.ctx.storage.by_period(year, limit=10, offset=10)
        self.assertEqual(len(page1), 10)
        ids1 = {b.id for b in page1}
        ids2 = {b.id for b in page2}
        self.assertFalse(ids1 & ids2)  # no overlap between pages


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ThreadedFetchTest(unittest.TestCase):
    """The regression test for the SQLite cross-thread bug: a real QThread
    worker fetches over HTTP and writes to its OWN connection; the main
    connection then sees the content via WAL."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_thr_"))
        # Persist settings with network ON so the worker's fresh context allows fetch.
        cfg = Config(self.tmp / "home")
        cfg.save_settings(Settings(network_enabled=True, allow_page_fetch=True))
        self.ctx = ApplicationContext(cfg)
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="", title="placeholder", date_added=1_700_000_000, browser="Firefox"))
        # Local HTTP server serving one HTML page.
        html = (b"<html><head><title>Served</title>"
                b"<meta property='og:site_name' content='Local'></head>"
                b"<body><article><p>hello from loopback bm25</p></article></body></html>")

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # Point the bookmark at the local server.
        self.ctx.storage.conn.execute(
            "UPDATE bookmarks SET url=? WHERE id=?",
            (f"http://127.0.0.1:{self.port}/", self.bid))
        self.ctx.storage.conn.commit()

    def tearDown(self):
        self.server.shutdown()
        self.ctx.close()

    def test_worker_fetches_cross_thread_without_error(self):
        from chronos.gui.workers import FetchWorker
        loop = QEventLoop()
        result = {"ok": None, "err": None}
        w = FetchWorker(self.ctx.config.app_dir, self.bid)
        w.done.connect(lambda bid: (result.__setitem__("ok", bid), loop.quit()))
        w.failed.connect(lambda bid, msg: (result.__setitem__("err", msg), loop.quit()))
        w.start()
        loop.exec()
        w.wait(3000)
        self.assertIsNone(result["err"], f"worker failed: {result['err']}")
        self.assertEqual(result["ok"], self.bid)
        # Main-thread connection now sees the fetched content (WAL).
        bm = self.ctx.storage.get(self.bid)
        self.assertTrue(bm.has_content)
        self.assertIn("bm25", (bm.page_text or ""))


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ReaderEscapeTest(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_esc_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_reader_escapes_injected_markup(self):
        from chronos.gui.reader_panel import ReaderPanel
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x.test", title="t", date_added=1_700_000_000,
            browser="Firefox"))
        page = extract_content(
            "<html><body><article><p>ok</p></article></body></html>",
            "https://x.test")
        page.text = "<script>alert(1)</script>\nsafe line"
        self.ctx.content.store_extracted(bid, page)
        panel = ReaderPanel(network_allowed=False)
        panel.show_bookmark(self.ctx.storage.get(bid))
        html = panel.body.toHtml()
        # The raw <script> tag must not survive as live markup.
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("alert(1)", panel.body.toPlainText())


if __name__ == "__main__":
    unittest.main(verbosity=2)
