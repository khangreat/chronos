"""v0.8 tests: settings dialog + apply flow, runtime theme switch, quotes
viewer, and feed-driven view reload. All offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.config import Config, Settings  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False

RSS = ("<?xml version='1.0'?><rss version='2.0'><channel><title>F</title>"
       "<link>https://s/</link><item><title>hi</title><link>https://s/a</link>"
       "<pubDate>Mon, 03 Feb 2025 08:00:00 +0000</pubDate></item></channel></rss>")


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class WiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_wire_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x.test", title="X", date_added=1_700_000_000,
            browser="Firefox"))

    def tearDown(self):
        self.ctx.close()

    def _window(self):
        from chronos.gui.main_window import MainWindow
        return MainWindow(self.ctx)

    def test_settings_dialog_reflects_controls(self):
        from chronos.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(Settings(network_enabled=True, allow_page_fetch=True))
        out = dlg.result_settings()
        self.assertTrue(out.network_enabled)
        self.assertTrue(out.allow_page_fetch)
        # master off disables sub-toggles
        dlg.master.setChecked(False)
        self.assertFalse(dlg.page.isEnabled())

    def test_apply_settings_persists_and_updates_policy(self):
        w = self._window()
        w._show_bookmark(self.bid)
        self.assertFalse(self.ctx.network.is_allowed("page_fetch"))
        self.assertFalse(w.reader.fetch_btn.isEnabled())

        w.apply_settings(Settings(network_enabled=True, allow_page_fetch=True))
        # live policy updated
        self.assertTrue(self.ctx.network.is_allowed("page_fetch"))
        # reader fetch now enabled for the no-content bookmark
        self.assertTrue(w.reader.fetch_btn.isEnabled())
        # persisted to disk
        reloaded = Config(self.tmp / "home").load_settings()
        self.assertTrue(reloaded.network_enabled and reloaded.allow_page_fetch)

    def test_runtime_theme_switch(self):
        from chronos.gui.theme.tokens import THEMES
        w = self._window()
        w.apply_settings(Settings(theme="midnight"))
        self.assertEqual(w.tokens["accent"], THEMES["midnight"]["accent"])
        # delegate picked up the new tokens
        self.assertEqual(w.stream.view.itemDelegate().t["accent"],
                         THEMES["midnight"]["accent"])

    def test_quotes_dialog_formats_quote_and_citation(self):
        from chronos.gui.quotes_dialog import QuotesDialog
        self.ctx.content  # ensure services import
        self.ctx.snippets.capture(self.bid, "a captured line", locator="p2")
        quotes = self.ctx.provider().list_quotes()
        dlg = QuotesDialog(quotes)
        self.assertEqual(dlg.list.count(), 1)
        text = dlg.formatted(quotes[0])
        self.assertIn("a captured line", text)
        self.assertIn("p2", text)
        self.assertIn("X", text)  # source title in citation line

    def test_feed_add_reloads_views(self):
        w = self._window()
        self.ctx.feeds.subscribe_from_text("https://s/feed", RSS)
        w._reload_views()  # must not raise; timeline reflects new item
        self.assertGreaterEqual(self.ctx.bookmarks.count(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
