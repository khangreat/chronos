"""i18n + RTL tests: catalog loading, English fallback, RTL detection, and the
live language switch (layout direction flip + retranslation).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.gui import i18n  # noqa: E402
from chronos.core.config import Settings  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


class TranslatorTest(unittest.TestCase):
    def test_english_base(self):
        t = i18n.Translator("en")
        self.assertEqual(t.tr("menu.file"), "File")

    def test_arabic_overrides(self):
        t = i18n.Translator("ar")
        self.assertEqual(t.tr("menu.file"), "ملف")
        self.assertTrue(t.is_rtl)

    def test_missing_key_returns_key(self):
        t = i18n.Translator("en")
        self.assertEqual(t.tr("no.such.key"), "no.such.key")

    def test_brahui_scaffold_falls_back_to_english(self):
        t = i18n.Translator("brh")
        self.assertTrue(t.is_rtl)                       # RTL layout
        self.assertEqual(t.tr("menu.file"), "File")     # English until authored

    def test_format_args(self):
        t = i18n.Translator("en")
        self.assertEqual(t.tr("status.online"), "online")
        self.assertIn("5", t.tr("status.summary", n=5, v=5, net="online"))

    def test_available_locales(self):
        locs = i18n.available_locales()
        self.assertIn("en", locs)
        self.assertIn("ar", locs)
        self.assertIn("brh", locs)


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class RtlSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_locale("en")
        self.app.setLayoutDirection(Qt.LeftToRight)
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_i18n_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        i18n.set_locale("en")
        self.ctx.close()

    def _window(self):
        from chronos.gui.main_window import MainWindow
        return MainWindow(self.ctx)

    def test_switch_to_arabic_flips_direction_and_text(self):
        w = self._window()
        self.assertEqual(w.search.placeholderText(),
                         "Search titles, URLs, and page text…")
        w.apply_settings(Settings(language="ar"))
        self.assertEqual(self.app.layoutDirection(), Qt.RightToLeft)
        self.assertEqual(w.search.placeholderText(),
                         "ابحث في العناوين والروابط ونص الصفحة…")
        self.assertEqual(w._menus["menu.file"].title(), "ملف")

    def test_switch_back_to_english_restores_ltr(self):
        w = self._window()
        w.apply_settings(Settings(language="ar"))
        w.apply_settings(Settings(language="en"))
        self.assertEqual(self.app.layoutDirection(), Qt.LeftToRight)
        # intent kept: English title restored; the & is its Alt-key mnemonic (v0.29)
        self.assertEqual(w._menus["menu.file"].title().replace("&", ""), "File")

    def test_brahui_is_rtl_but_text_english_until_authored(self):
        w = self._window()
        w.apply_settings(Settings(language="brh"))
        self.assertEqual(self.app.layoutDirection(), Qt.RightToLeft)  # RTL layout
        self.assertEqual(w.search.placeholderText(),                  # English fallback
                         "Search titles, URLs, and page text…")


if __name__ == "__main__":
    unittest.main(verbosity=2)
