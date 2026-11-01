"""GUI: the reader's Related panel populates from the related service and
navigates when an item is activated. Runs headless (offscreen).
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

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ReaderRelatedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_gui_rel_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _bm(self, url, title, text):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=url, title=title, date_added=1, browser="F"))
        self.ctx.storage.conn.execute(
            "UPDATE bookmarks SET page_text=? WHERE id=?", (text, bid))
        self.ctx.storage.conn.commit()
        return bid

    def _win(self):
        from chronos.gui.main_window import MainWindow
        return MainWindow(self.ctx)

    def test_related_panel_populates_and_navigates(self):
        a = self._bm("https://x/a", "Brahui phonology",
                     "retroflex consonants Brahui Dravidian language")
        b = self._bm("https://x/b", "Dravidian retroflex",
                     "retroflex Dravidian consonants Brahui similar")
        self._bm("https://x/c", "Pasta recipe", "boil water salt pasta drain")
        w = self._win()
        w._show_bookmark(a)
        # the related list shows the similar doc, and it's clickable
        self.assertGreaterEqual(w.reader.related_list.count(), 1)
        first = w.reader.related_list.item(0)
        # activating it navigates the reader to that resource
        w.reader.related_list.itemActivated.emit(first)
        self.assertEqual(w.reader._bm.id, b)

    def test_counts_shown_in_meta(self):
        a = self._bm("https://x/a", "t", "some content about testing things")
        self.ctx.snippets.capture(a, "a quote")
        self.ctx.takeaways.add(a, "my point")
        w = self._win()
        w._show_bookmark(a)
        txt = w.reader.quote_count.text()
        self.assertIn("quote", txt)
        self.assertIn("takeaway", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
