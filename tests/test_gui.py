"""GUI smoke test — offscreen construction + interaction, part of the gate.

Skips cleanly if PySide6 isn't installed, so the headless Core suite still runs
anywhere. When PySide6 is present, it proves the window builds, panels populate,
selection drives the reader, search works, and the fetch button honours the
network gate — all without a display.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # pragma: no cover
    _HAS_QT = False

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.web.extract import extract_content  # noqa: E402
from tests.fixtures import build_firefox_places  # noqa: E402

_ARTICLE = (
    "<html><head><title>FTS5</title>"
    "<meta property='og:site_name' content='SQLite Docs'>"
    "<meta name='author' content='Jane Roe'></head>"
    "<body><article><p>FTS5 ranks with bm25.</p></article></body></html>"
)


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class GuiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chronos_gui_"))
        self.ctx = ApplicationContext.for_dir(self.dir / "home")
        fx = self.dir / "places.sqlite"
        build_firefox_places(fx)
        self.ctx.bookmarks.import_from("firefox", fx)
        bm = self.ctx.storage.get_by_url("https://docs.python.org")
        self.ctx.content.store_extracted(
            bm.id, extract_content(_ARTICLE, "https://docs.python.org"))

    def tearDown(self):
        self.ctx.close()

    def _window(self):
        from chronos.gui.main_window import MainWindow
        w = MainWindow(self.ctx)
        w.resize(1100, 720)
        return w

    def test_window_builds_and_stream_populates(self):
        w = self._window()
        self.assertGreater(w.stream.count(), 0)

    def test_selection_drives_reader(self):
        w = self._window()
        bm = self.ctx.storage.get_by_url("https://docs.python.org")
        w._show_bookmark(bm.id)
        self.assertIn("Python", w.reader.title.text())
        self.assertTrue(w.reader.body.toPlainText().strip())

    def test_search_updates_stream(self):
        w = self._window()
        w.search.setText("python")
        w._run_search()
        self.assertGreater(w.stream.count(), 0)

    def test_fetch_button_disabled_when_network_off(self):
        w = self._window()
        # a bookmark with no content, network off -> fetch stays disabled
        bm = self.ctx.storage.get_by_url("https://github.com")
        w.reader.show_bookmark(bm)
        self.assertFalse(w.reader.fetch_btn.isEnabled())

    def test_favorite_toggle_persists(self):
        w = self._window()
        bm = self.ctx.storage.get_by_url("https://github.com")
        w._toggle_fav(bm.id, True)
        self.assertTrue(self.ctx.storage.get(bm.id).is_favorite)

    def test_theme_qss_builds(self):
        from chronos.gui.theme.tokens import THEMES, build_qss
        for name in THEMES:
            self.assertIn("QMainWindow", build_qss(THEMES[name]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
