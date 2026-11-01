"""Design regression guards (v0.28 design pass). Each test pins a fixed UI bug
so it fails if the bug returns: labels painting the window colour inside the
reader, the reader crushing the stream, raw horizontal scrollbars, Windows-
unsafe date formatting, keyboard browsing, the empty state, RTL painting, and
untranslated new copy.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.gui.theme.tokens import DUSK, build_qss  # noqa: E402

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


class QssTest(unittest.TestCase):
    def test_labels_never_paint_window_colour(self):
        qss = build_qss(DUSK)
        self.assertIn("QLabel { background: transparent; }", qss)
        # the blanket rule that painted every label inside cards must not return
        self.assertNotIn("QMainWindow, QWidget {", qss)

    def test_horizontal_scrollbars_styled(self):
        self.assertIn("QScrollBar:horizontal", build_qss(DUSK))

    def test_disabled_primary_not_brass(self):
        self.assertIn("#PrimaryButton:disabled", build_qss(DUSK))


class CopyTest(unittest.TestCase):
    def test_byline_is_a_sentence_and_windows_safe(self):
        from chronos.gui.reader_panel import byline_for
        ts = int(dt.datetime(2026, 3, 10, 12).timestamp())
        bm = Bookmark(url="https://m.social/@x/1", title="t", date_added=ts,
                      browser="Capture", site_name="m.social", byline="@x",
                      kind="social_post")
        self.assertEqual(byline_for(bm), "Post by @x on m.social, 10 March 2026")
        art = Bookmark(url="https://lemonde.fr/a", title="t", date_added=ts,
                       browser="F", site_name="Le Monde", kind="article")
        self.assertEqual(byline_for(art), "Article in Le Monde, 10 March 2026")

    def test_no_platform_specific_strftime(self):
        for f in (ROOT / "chronos").rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            for bad in ("%-d", "%-m", "%-H", "%-I"):
                self.assertNotIn(bad, src, f"{f.name} uses {bad} (crashes on Windows)")

    def test_provenance_sentences(self):
        from chronos.gui.reader_panel import provenance_sentences
        t1 = int(dt.datetime(2026, 3, 10).timestamp())
        t2 = int(dt.datetime(2026, 3, 14).timestamp())
        out = provenance_sentences([
            {"method": "platform_saved", "source": "reddit", "acquired_at": t2},
            {"method": "browser_bookmark", "source": "firefox", "acquired_at": t1},
            {"method": "browser_bookmark", "source": "firefox", "acquired_at": t1},
        ])
        self.assertEqual(out, ["Bookmarked in Firefox, 10 Mar 2026",
                               "Saved on Reddit, 14 Mar 2026"])  # oldest first, deduped

    def test_new_copy_is_in_every_catalog(self):
        loc = ROOT / "chronos/gui/locale"
        en = json.loads((loc / "en.json").read_text(encoding="utf-8"))
        keys = [k for k in en if k.split(".")[0] in ("reader", "welcome", "stream")
                and k not in ("section.stream",)]
        self.assertGreater(len(keys), 20)
        for name in ("ar.json", "brh.json"):
            cat = json.loads((loc / name).read_text(encoding="utf-8"))
            missing = [k for k in keys if k not in cat]
            self.assertEqual(missing, [], f"{name} lacks {missing}")


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_design_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _seed(self, n=3):
        ids = []
        for i in range(n):
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://x.example/{i}", title=f"Item {i}",
                date_added=int(dt.datetime(2026, 3, 10 + i).timestamp()),
                browser="Firefox"))
            ids.append(bid)
        return ids

    def _win(self, w=1280, h=800):
        from chronos.gui.main_window import MainWindow
        win = MainWindow(self.ctx)
        win.resize(w, h)
        win.show()
        self.app.processEvents()
        return win

    def test_reader_does_not_crush_stream(self):
        self._seed()
        win = self._win(1024, 700)
        sizes = win.splitter.sizes()
        self.assertGreaterEqual(sizes[0], 150)   # timeline readable
        self.assertGreaterEqual(sizes[1], 280)   # stream titles readable
        win.close()

    def test_no_horizontal_scrollbars_in_index_panes(self):
        win = self._win()
        self.assertEqual(win.stream.view.horizontalScrollBarPolicy(),
                         Qt.ScrollBarAlwaysOff)
        self.assertEqual(win.timeline.tree.horizontalScrollBarPolicy(),
                         Qt.ScrollBarAlwaysOff)
        win.close()

    def test_keyboard_browsing_opens_item(self):
        ids = self._seed()
        win = self._win()
        model = win.stream.model
        row = next(r for r in range(model.rowCount())
                   if model.bookmark_at(r) is not None)
        win.stream.view.setCurrentIndex(model.index(row, 0))
        self.assertIsNotNone(win.reader._bm)
        self.assertIn(win.reader._bm.id, ids)
        win.close()

    def test_redundant_group_header_suppressed(self):
        self._seed()
        win = self._win()
        win._show_period(2026, 3)
        delegate = win.stream.view.itemDelegate()
        self.assertEqual(delegate.suppress_header.lower(), "march 2026")
        win.close()

    def test_empty_archive_shows_welcome_not_dead_controls(self):
        win = self._win()
        self.assertFalse(win.reader.title.isVisible())
        self.assertFalse(win.reader.open_btn.isVisible())
        self.assertIn("archive starts here", win.reader.body.toPlainText())
        win.close()

    def test_rtl_stream_paints(self):
        from chronos.core.config import Settings
        self._seed()
        win = self._win()
        win.apply_settings(Settings(language="ar"))
        self.app.processEvents()
        self.assertFalse(win.stream.view.grab().isNull())   # mirrored paint path ran
        win.apply_settings(Settings(language="en"))
        win.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
