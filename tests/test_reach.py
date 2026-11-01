"""v0.29 "Everything in reach": Facebook import, the source catalogue and Import
window, library filters, meaning search, export, browser-capture setup, and
accessibility guards (contrast, text scaling, accessible names, and parity
between command-line importers and the GUI).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.importers.platform.facebook import fix_text, parse_facebook  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


def _moji(s: str) -> str:
    """What Facebook actually writes: UTF-8 bytes as Latin-1 code points."""
    return s.encode("utf-8").decode("latin-1")


def make_fb_export(root: Path) -> Path:
    d = root / "facebook-me"
    posts = d / "your_activity_across_facebook" / "posts"
    saved = d / "your_activity_across_facebook" / "saved_items_and_collections"
    comments = d / "your_activity_across_facebook" / "comments_and_reactions"
    for p in (posts, saved, comments):
        p.mkdir(parents=True)
    (posts / "your_posts__check_ins__photos_and_videos_1.json").write_text(json.dumps([
        {"timestamp": 1700000000, "data": [{"post": _moji("براہوئی زبان پر ایک نوٹ")}],
         "title": "Me updated status."},
        {"timestamp": 1700000100, "data": [{"post": "Worth reading on Dravidian roots"}],
         "attachments": [{"data": [{"external_context": {
             "url": "https://example.org/dravidian", "name": "Dravidian roots"}}]}]},
        {"timestamp": 1700000200, "attachments": [{"data": [{"media": {"uri": "x.jpg"}}]}]},
    ]), encoding="utf-8")
    (saved / "your_saved_items.json").write_text(json.dumps({"saves_v2": [
        {"timestamp": 1700000300, "title": "Me saved a link.",
         "attachments": [{"data": [{"external_context": {
             "url": "https://news.example/brahui", "name": "Brahui news"}}]}]}]}),
        encoding="utf-8")
    (comments / "comments.json").write_text(json.dumps({"comments_v2": [
        {"timestamp": 1700000400, "title": "Me commented on a post.",
         "data": [{"comment": {"comment": _moji("بہت خوب"), "author": "Me"}}]}]}),
        encoding="utf-8")
    (comments / "likes_and_reactions_1.json").write_text(json.dumps([
        {"timestamp": 1700000500, "title": "Me liked a post."}]), encoding="utf-8")
    return d


class FacebookParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_fb_"))
        self.dir = make_fb_export(self.tmp)

    def test_mojibake_repaired(self):
        self.assertEqual(fix_text(_moji("ال")), "ال")
        self.assertEqual(fix_text("plain ascii"), "plain ascii")
        self.assertEqual(fix_text("ال"), "ال")          # already-correct text untouched

    def test_parse_folder(self):
        items = parse_facebook(self.dir)
        kinds = sorted(i.kind for i in items)
        self.assertEqual(kinds, ["comment", "post", "post", "saved"])  # photo-only + likes skipped
        post = next(i for i in items if i.kind == "post" and i.text.startswith("براہوئی"))
        self.assertTrue(post.url.startswith("fb-post://"))
        self.assertEqual(next(i for i in items if i.kind == "comment").text, "بہت خوب")

    def test_parse_zip_equals_folder(self):
        z = self.tmp / "fb.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in self.dir.rglob("*.json"):
                zf.write(f, f.relative_to(self.dir))
        self.assertEqual(sorted(i.url for i in parse_facebook(z)),
                         sorted(i.url for i in parse_facebook(self.dir)))


class FacebookImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_fbi_"))
        self.dir = make_fb_export(self.tmp)
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_import_kinds_links_provenance(self):
        r = self.ctx.platform_import.import_facebook(self.dir)
        self.assertEqual(r.resources, 4)
        saved = self.ctx.storage.get_by_url("https://news.example/brahui")
        self.assertEqual(saved.kind, "webpage")
        self.assertIn("platform_saved",
                      {a["method"] for a in self.ctx.provenance.for_bookmark(saved.id)})
        # a shared link becomes its own resource, linked from the post
        page = self.ctx.storage.get_by_url("https://example.org/dravidian")
        self.assertIsNotNone(page)
        posts = self.ctx.resources.by_kind("social_post")
        self.assertTrue(any(page.id in [b.id for _, b in self.ctx.resources.outgoing(p.id)]
                            for p in posts))
        self.assertEqual(len(self.ctx.resources.by_kind("social_comment")), 1)
        self.assertTrue(self.ctx.search.search("براہوئی"))     # repaired text is searchable

    def test_reimport_noop(self):
        self.ctx.platform_import.import_facebook(self.dir)
        n = self.ctx.storage.count()
        r2 = self.ctx.platform_import.import_facebook(self.dir)
        self.assertTrue(r2.already_imported)
        self.assertEqual(self.ctx.storage.count(), n)


class CatalogueTest(unittest.TestCase):
    def test_every_cli_importer_is_in_the_gui(self):
        import chronos.cli as cli
        from chronos.services.sources import file_sources
        ids = {s.id for s in file_sources()}
        cli_to_gui = {"import-reddit": "reddit", "import-x": "x",
                      "import-mastodon": "mastodon", "import-bluesky": "bluesky",
                      "import-facebook": "facebook",
                      "takeout": "takeout", "inbox": "inbox"}
        for cmd in cli.COMMANDS:
            if cmd.startswith("import-") or cmd in ("takeout", "inbox"):
                self.assertIn(cmd, cli_to_gui, f"new CLI importer {cmd!r}: add a GUI source")
                self.assertIn(cli_to_gui[cmd], ids)
        self.assertIn("facebook", ids)

    def test_every_source_explains_itself(self):
        from chronos.services.sources import file_sources
        for s in file_sources():
            self.assertGreater(len(s.how), 40, s.id)
            self.assertIn(s.pick, ("file", "folder", "either", "many", "none"))


class AccessibilityTokenTest(unittest.TestCase):
    @staticmethod
    def _cr(a, b):
        def lum(h):
            h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        hi, lo = sorted([lum(a), lum(b)], reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def test_all_text_passes_wcag_aa(self):
        from chronos.gui.theme.tokens import THEMES
        for name, t in THEMES.items():
            for fg in ("text", "text_muted", "text_faint", "accent", "link", "danger"):
                for bg in ("bg", "surface", "surface_alt"):
                    self.assertGreaterEqual(
                        self._cr(t[fg], t[bg]), 4.5, f"{name}: {fg} on {bg}")

    def test_high_contrast_theme(self):
        from chronos.gui.theme.tokens import THEMES
        t = THEMES["contrast"]
        for fg in ("text", "text_muted", "text_faint"):
            self.assertGreaterEqual(self._cr(t[fg], t["surface"]), 9.0)

    def test_text_size_scales_stylesheet(self):
        import re
        from chronos.gui.theme.tokens import DUSK, build_qss, with_scale
        small = [int(x) for x in re.findall(r"font-size: (\d+)px", build_qss(DUSK))]
        big = [int(x) for x in re.findall(r"font-size: (\d+)px",
                                          build_qss(with_scale(DUSK, "larger")))]
        self.assertGreater(sum(big), sum(small) * 1.2)


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class GuiReachTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_reach_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _win(self):
        from chronos.gui.main_window import MainWindow
        w = MainWindow(self.ctx); w.resize(1280, 800)
        return w

    def test_import_window_runs_sources(self):
        from chronos.gui.import_dialog import ImportDialog
        fb = make_fb_export(self.tmp)
        csv = self.tmp / "saved_posts.csv"
        csv.write_text("id,permalink\nt3_a,/r/brahui/comments/a/note/\n", encoding="utf-8")
        dlg = ImportDialog(self.ctx, sync=True)
        hits = []
        dlg.imported.connect(lambda: hits.append(1))
        dlg.run_source("facebook", str(fb))
        self.assertIn("4 items read", dlg.status_text("facebook"))
        dlg.run_source("reddit", str(csv))
        self.assertIn("1 item read", dlg.status_text("reddit"))  # v0.30: whole export, not only saved
        dlg.run_source("reddit", str(self.tmp / "missing.csv"))
        self.assertIn("Couldn’t import", dlg.status_text("reddit"))   # error shown, no crash
        self.assertEqual(len(hits), 2)

    def test_library_filters(self):
        self.ctx.platform_import.import_facebook(make_fb_export(self.tmp))
        w = self._win()
        w.timeline.reload()
        labels = []
        it = w.timeline.library.invisibleRootItem()
        for i in range(it.childCount()):
            top = it.child(i); labels.append(top.text(0))
            labels += [top.child(j).text(0) for j in range(top.childCount())]
        self.assertIn("Comments", labels)
        self.assertIn("Facebook", labels)
        w._show_library("source", "facebook")
        self.assertEqual(w.stream.count(), self.ctx.storage.count())
        w._show_library("kind", "social_comment")
        self.assertEqual(w.stream.count(), 1)

    def test_meaning_search_mode(self):
        for i, (t, x) in enumerate((("Brahui phonology", "retroflex Brahui Dravidian"),
                                    ("Pasta", "boil water salt"))):
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://x/{i}", title=t, date_added=1, browser="F"))
            self.ctx.storage.conn.execute("UPDATE bookmarks SET page_text=? WHERE id=?",
                                          (x, bid))
        self.ctx.storage.conn.commit()
        w = self._win()
        w._set_search_mode("meaning")
        w.search.setText("Dravidian")
        w._run_search()
        self.assertEqual(w.stream.model.bookmark_at(
            next(r for r in range(w.stream.model.rowCount())
                 if w.stream.model.bookmark_at(r))).title, "Brahui phonology")
        self.assertTrue(w.act_meaning.isChecked())

    def test_every_menu_action_has_a_name(self):
        w = self._win()
        for key, a in w._menu_actions:
            self.assertTrue(a.text().replace("&", "").strip(), key)

    def test_icon_buttons_have_accessible_names(self):
        w = self._win()
        for b in (w.reader.fav_btn, w.reader.more_btn, w.search_mode):
            self.assertTrue(b.accessibleName(), b.objectName())

    def test_export_facebook_post_has_no_open(self):
        self.ctx.platform_import.import_facebook(make_fb_export(self.tmp))
        post = next(b for b in self.ctx.resources.by_kind("social_post")
                    if b.url.startswith("fb-post://"))
        w = self._win()
        w._show_bookmark(post.id)
        self.assertFalse(w.reader.open_btn.isEnabled())

    def test_export_text_is_read_not_fetched(self):
        # a post's own text came with the export: show it, don't ask to fetch
        self.ctx.platform_import.import_facebook(make_fb_export(self.tmp))
        post = next(b for b in self.ctx.resources.by_kind("social_post")
                    if b.url.startswith("fb-post://") and "براہوئی" in (b.page_text or ""))
        w = self._win()
        w._show_bookmark(post.id)
        body = w.reader.body.toPlainText()
        self.assertIn("براہوئی", body)
        self.assertNotIn("Networking is off", body)
        self.assertFalse(w.reader.fetch_btn.isEnabled())

    def test_comment_titled_by_its_words(self):
        self.ctx.platform_import.import_facebook(make_fb_export(self.tmp))
        c = self.ctx.resources.by_kind("social_comment")[0]
        self.assertEqual(c.title, "بہت خوب")

    def test_rows_remeasure_on_text_size(self):
        from chronos.gui.stream_model import ENTRY_ROLE  # noqa: F401
        for i in range(3):
            self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://x/{i}", title=f"t{i}", date_added=1700000000 + i,
                browser="F"))
        w = self._win(); w.show(); self.app.processEvents()
        w._show_period(2023, 11)
        v = w.stream.view
        row = next(r for r in range(w.stream.model.rowCount())
                   if w.stream.model.bookmark_at(r))
        before = v.visualRect(w.stream.model.index(row, 0)).height()
        w._step_text(+1); w._step_text(+1); self.app.processEvents()
        after = v.visualRect(w.stream.model.index(row, 0)).height()
        self.assertGreater(after, before)

    def test_capture_setup(self):
        from chronos.gui.capture_dialog import CaptureDialog
        d = CaptureDialog()
        dest = d.unpack(str(self.tmp))
        self.assertTrue((dest / "manifest.json").exists())
        self.assertIn("Paste the extension ID", d.connect_extension("", "chrome"))
        home = self.tmp / "fakehome"
        msg = d.connect_extension("abcdefghijklmnop", "chrome", home=home)
        if not sys.platform.startswith("win"):
            self.assertTrue(msg.startswith("Connected"))
            self.assertTrue(list(home.rglob("com.chronos.capture.json")))

    def test_text_size_step(self):
        w = self._win()
        w._step_text(+1)
        self.assertEqual(self.ctx.config.settings.text_size, "large")
        w._step_text(0)
        self.assertEqual(self.ctx.config.settings.text_size, "default")


if __name__ == "__main__":
    unittest.main(verbosity=2)
