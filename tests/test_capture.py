"""Capture tests: snippet storage, interop quote+citation for Nawishtar,
migration v4, and the reader capture flow through the GUI.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.web.extract import extract_content  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False

_HTML = ("<html><head><title>FTS5</title>"
         "<meta property='og:site_name' content='SQLite Docs'>"
         "<meta name='author' content='Jane Roe'>"
         "<meta property='article:published_time' content='2024-05-01T09:00:00Z'>"
         "</head><body><article><p>bm25 ranks results.</p></article></body></html>")


class SnippetCoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_cap_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5",
            date_added=1_700_000_000, browser="Firefox"))
        self.ctx.content.store_extracted(
            self.bid, extract_content(_HTML, "https://sqlite.org/fts5.html"))

    def tearDown(self):
        self.ctx.close()

    def test_migration_v4_snippets(self):
        self.assertGreaterEqual(self.ctx.storage.version, 4)
        self.assertEqual(self.ctx.snippets.all(), [])

    def test_capture_and_list(self):
        s = self.ctx.snippets.capture(self.bid, "  bm25 ranks results.  ",
                                      note="key idea", locator="para 1")
        self.assertEqual(s.quote, "bm25 ranks results.")  # trimmed
        self.assertEqual(len(self.ctx.snippets.for_bookmark(self.bid)), 1)

    def test_empty_quote_rejected(self):
        with self.assertRaises(ValueError):
            self.ctx.snippets.capture(self.bid, "   ")

    def test_quote_carries_source_citation(self):
        s = self.ctx.snippets.capture(self.bid, "bm25 ranks results.",
                                      locator="para 1")
        q = self.ctx.provider().get_quote(s.id)
        self.assertEqual(q["quote"], "bm25 ranks results.")
        self.assertEqual(q["locator"], "para 1")
        # source citation is full CSL-JSON, ready for Nawishtar
        self.assertEqual(q["source"]["type"], "webpage")
        self.assertEqual(q["source"]["container-title"], "SQLite Docs")
        self.assertEqual(q["source"]["issued"]["date-parts"][0][0], 2024)

    def test_list_quotes(self):
        self.ctx.snippets.capture(self.bid, "one")
        self.ctx.snippets.capture(self.bid, "two")
        self.assertEqual(len(self.ctx.provider().list_quotes()), 2)

    def test_deleting_source_cascades_snippets(self):
        s = self.ctx.snippets.capture(self.bid, "gone soon")
        self.ctx.storage.conn.execute("DELETE FROM bookmarks WHERE id=?", (self.bid,))
        self.ctx.storage.conn.commit()
        self.assertIsNone(self.ctx.storage.get_snippet(s.id))  # ON DELETE CASCADE


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ReaderCaptureFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_capgui_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5",
            date_added=1_700_000_000, browser="Firefox"))
        self.ctx.content.store_extracted(
            self.bid, extract_content(_HTML, "https://sqlite.org/fts5.html"))

    def tearDown(self):
        self.ctx.close()

    def test_select_in_reader_and_capture(self):
        from chronos.gui.main_window import MainWindow
        w = MainWindow(self.ctx)
        w._show_bookmark(self.bid)
        # select all reader text, then trigger the quote action
        w.reader.body.selectAll()
        w.reader._quote()
        snips = self.ctx.snippets.for_bookmark(self.bid)
        self.assertEqual(len(snips), 1)
        self.assertIn("bm25", snips[0].quote)
        # the reader shows the running count
        self.assertIn("1 quote", w.reader.quote_count.text())

    def test_empty_selection_captures_nothing(self):
        from chronos.gui.main_window import MainWindow
        w = MainWindow(self.ctx)
        w._show_bookmark(self.bid)
        w.reader.body.textCursor().clearSelection()
        w._save_quote(self.bid, "")
        self.assertEqual(len(self.ctx.snippets.for_bookmark(self.bid)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
