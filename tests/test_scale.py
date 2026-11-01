"""Scale + messy-data tests. Confirms the model/delegate handle large, varied,
and adversarial data without breaking — and that the model stays flat in memory
(no widget per row).
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

# A deliberately varied set: RTL scripts, CJK, very long text, empty title,
# odd schemes, whitespace, unicode punctuation.
VARIED = [
    ("https://brh.example/بلوچی", "براہوئی وِکی — ٹیسٹ"),          # Brahui (RTL)
    ("https://ar.example/مقالة", "العربية عنوان طويل جدا"),        # Arabic (RTL)
    ("https://cjk.example/文章", "日本語のタイトル 测试 테스트"),      # CJK
    ("https://long.example/x", "L" + "o" * 400 + "ng title"),      # very long
    ("https://empty.example/", ""),                                # empty title
    ("ftp://weird.example/file", "ftp scheme"),                    # non-http
    ("https://space.example/  ", "   leading/trailing   "),        # whitespace
    ("https://emoji.example/x", "plain ascii only"),               # control
    ("https://dup.example/x", "dup one"),
    ("https://dup.example/x", "dup two (same url)"),               # dedupe target
]


class VariedDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_varied_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        bms = [Bookmark(url=u, title=t, date_added=1_700_000_000 + i * 3600,
                        browser="Firefox") for i, (u, t) in enumerate(VARIED)]
        self.inserted = self.ctx.storage.import_bookmarks(bms)

    def tearDown(self):
        self.ctx.close()

    def test_varied_data_imports_and_dedupes(self):
        # 10 rows, one duplicate url -> 9 stored
        self.assertEqual(self.inserted, 9)

    def test_rtl_and_cjk_searchable(self):
        self.assertTrue(self.ctx.search.search("براہوئی"))
        self.assertTrue(self.ctx.search.search("日本語"))

    def test_long_and_empty_titles_dont_break_reads(self):
        rows = self.ctx.storage.by_period(
            self.ctx.storage.year_counts()[0][0], limit=500)
        self.assertTrue(rows)  # no crash building bookmarks from messy rows


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ModelDelegateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bookmarks(self, n):
        return [Bookmark(id=i, url=f"https://e.test/{i}", title=f"Item {i}",
                         date_added=1_704_067_200 + i * 3600, browser="Firefox",
                         is_favorite=(i % 7 == 0))
                for i in range(n)]

    def test_model_interleaves_headers_and_items(self):
        from chronos.gui.stream_model import BookmarkListModel
        m = BookmarkListModel()
        m.set_bookmarks(self._bookmarks(50))
        # rows = items + at least one header
        self.assertGreater(m.rowCount(), m.item_count())
        self.assertEqual(m.item_count(), 50)

    def test_headers_not_selectable(self):
        from chronos.gui.stream_model import BookmarkListModel, ENTRY_ROLE
        from PySide6.QtCore import Qt
        m = BookmarkListModel()
        m.set_bookmarks(self._bookmarks(5))
        header_rows = [r for r in range(m.rowCount())
                       if m.data(m.index(r), ENTRY_ROLE).kind == "header"]
        self.assertTrue(header_rows)
        for r in header_rows:
            self.assertFalse(m.flags(m.index(r)) & Qt.ItemIsSelectable)

    def test_large_model_is_flat_no_widgets(self):
        # 30k items load into the model; the view must not create 30k widgets.
        from chronos.gui.stream_panel import StreamPanel
        from chronos.gui.theme.tokens import THEMES
        panel = StreamPanel(THEMES["dusk"])
        panel.resize(500, 700)
        panel.set_bookmarks(self._bookmarks(30_000), "Big")
        self.assertEqual(panel.count(), 30_000)
        # QListView children stay a tiny fixed set (viewport, scrollbars),
        # never one-per-row.
        from PySide6.QtWidgets import QWidget
        child_widgets = panel.view.findChildren(QWidget)
        self.assertLess(len(child_widgets), 50,
                        f"view created too many widgets: {len(child_widgets)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
