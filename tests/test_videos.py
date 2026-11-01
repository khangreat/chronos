"""v0.32 "Videos for ytman": recognising videos in every URL form, finding the
videos inside saved pages, one item per video, start times, dedupe, the ytman
handoff, and the reader's video section.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.web.video import parse_video, videos_in_html  # noqa: E402

ID = "dQw4w9WgXcQ"
CANON = f"https://www.youtube.com/watch?v={ID}"

PAGE = f"""<html><head>
<meta property="og:video" content="https://www.youtube.com/embed/{ID}">
</head><body>
<p>A talk on Brahui phonology:</p>
<iframe src="https://www.youtube-nocookie.com/embed/{ID}?start=95"></iframe>
<p>Also see <a href="https://youtu.be/aaaaaaaaaaa?t=1m30s">this lecture</a>
and <a href="https://vimeo.com/76979871">a documentary</a>.</p>
<p>Plain text link: https://www.youtube.com/shorts/bbbbbbbbbbb</p>
<a href="https://example.org/not-a-video">other</a>
<a href="https://www.youtube.com/channel/UCxyz">a channel, not a video</a>
</body></html>"""

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


class ParseTest(unittest.TestCase):
    def test_every_form_is_one_video(self):
        forms = [f"https://www.youtube.com/watch?v={ID}", f"https://youtu.be/{ID}",
                 f"https://m.youtube.com/watch?v={ID}&feature=share",
                 f"https://www.youtube.com/shorts/{ID}", f"https://www.youtube.com/embed/{ID}",
                 f"https://www.youtube-nocookie.com/embed/{ID}",
                 f"https://music.youtube.com/watch?v={ID}&list=RD",
                 f"https://www.youtube.com/live/{ID}?si=abc"]
        self.assertEqual({parse_video(u).url for u in forms}, {CANON})

    def test_start_times(self):
        self.assertEqual(parse_video(f"https://youtu.be/{ID}?t=90").start, 90)
        self.assertEqual(parse_video(f"{CANON}&t=1m30s").start, 90)
        self.assertEqual(parse_video(f"{CANON}&t=1h2m3s").start, 3723)
        self.assertEqual(parse_video(f"https://www.youtube.com/embed/{ID}?start=95").start, 95)
        self.assertEqual(parse_video(f"{CANON}&t=90").url_at_start, f"{CANON}&t=90")

    def test_not_videos(self):
        for u in ("https://www.youtube.com/channel/UCxyz", "https://www.youtube.com/",
                  "https://example.org/watch?v=dQw4w9WgXcQ", "https://vimeo.com/about",
                  "https://youtu.be/short"):
            self.assertIsNone(parse_video(u), u)
        self.assertEqual(parse_video("https://player.vimeo.com/video/76979871").url,
                         "https://vimeo.com/76979871")

    def test_videos_in_page(self):
        found = videos_in_html(PAGE, "https://blog.example/post")
        ids = [f.video.video_id for f in found]
        self.assertEqual(ids, [ID, "aaaaaaaaaaa", "76979871", "bbbbbbbbbbb"])
        first = found[0]
        self.assertTrue(first.embedded)                  # og:video / iframe
        self.assertFalse(found[1].embedded)              # just a link
        self.assertEqual(found[1].video.start, 90)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_vid_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "h")
        self.page, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://blog.example/post", title="Brahui talks", date_added=1700000000,
            browser="Firefox"))

    def tearDown(self):
        self.ctx.close()

    def test_archive_links_page_to_its_videos(self):
        self.ctx.archive.archive_from_html(self.page, PAGE, "https://blog.example/post")
        vids = self.ctx.videos.videos_on(self.page)
        self.assertEqual(len(vids), 4)
        self.assertTrue(all(v.kind == "video" for v in vids))
        main = self.ctx.storage.get_by_url(CANON)
        on = self.ctx.videos.found_on(main.id)
        self.assertEqual(on[0]["url"], "https://blog.example/post")
        self.assertTrue(on[0]["embedded"])
        lec = self.ctx.storage.get_by_url("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertEqual(self.ctx.videos.found_on(lec.id)[0]["start"], 90)

    def test_bookmarked_video_variants_become_one(self):
        a, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=f"https://youtu.be/{ID}", title="t", date_added=1, browser="Chrome"))
        b, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=f"https://www.youtube.com/shorts/{ID}", title="t", date_added=2,
            browser="Firefox"))
        self.assertEqual(self.ctx.storage.get(a).kind, "video")     # classified on import
        self.ctx.curation.merge_all()
        left = [x for x in (self.ctx.storage.get(a), self.ctx.storage.get(b)) if x]
        self.assertEqual(len(left), 1)

    def test_scan_saved_pages_offline(self):
        self.ctx.archive.archive_from_html(self.page, "<p>nothing yet</p>", "https://blog.example/post")
        # replace the stored copy's content to simulate an older archive
        rec = self.ctx.storage.get_archive(self.page)
        import gzip
        Path(rec["path"] if isinstance(rec, dict) else rec.path).write_bytes(
            gzip.compress(PAGE.encode()))
        r = self.ctx.videos.scan_saved_pages()
        self.assertEqual(r["pages"], 1)
        self.assertEqual(len(self.ctx.videos.all_videos()), 4)

    def test_ytman_handoff_and_link_provider(self):
        self.ctx.archive.archive_from_html(self.page, PAGE, "https://blog.example/post")
        out = self.tmp / "for-ytman.json"
        n = self.ctx.videos.write_ytman_handoff(out, [self.page])  # a page contributes its videos
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(n, 4)
        self.assertEqual(data["target"], "ytman")
        v = next(x for x in data["videos"] if x["video_id"] == ID)
        self.assertEqual(v["found_on"][0]["title"], "Brahui talks")
        yt = self.ctx.provider().youtube_links()
        self.assertEqual(sorted(r.url for r in yt), sorted([
            CANON, "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "https://www.youtube.com/watch?v=bbbbbbbbbbb"]))       # Vimeo isn't YouTube

    def test_migration_backfills_video_kind(self):
        self.assertGreaterEqual(self.ctx.storage.version, 9)


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class ReaderVideosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_lists_videos_and_video_lists_pages(self):
        tmp = Path(tempfile.mkdtemp())
        ctx = ApplicationContext.for_dir(tmp / "h")
        try:
            page, _ = ctx.storage.upsert_bookmark(Bookmark(
                url="https://blog.example/post", title="Brahui talks", date_added=1,
                browser="F"))
            ctx.archive.archive_from_html(page, PAGE, "https://blog.example/post")
            from chronos.gui.main_window import MainWindow
            w = MainWindow(ctx)
            w._show_bookmark(page)
            self.assertEqual(w.reader.videos_list.count(), 4)
            self.assertIn("Videos in this page", w.reader.videos_header.text())
            lec = ctx.storage.get_by_url("https://www.youtube.com/watch?v=aaaaaaaaaaa")
            w._show_bookmark(lec.id)
            self.assertEqual(w.reader.videos_header.text(), "Found on")
            self.assertIn("(from 1:30)", w.reader.videos_list.item(0).text())
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
