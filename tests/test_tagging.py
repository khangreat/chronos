"""Auto-tagging tests: source + script + topical keyword tags across languages,
CJK bigram handling, merge-with-existing, and tag-based retrieval.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402


def _bm(ctx, url, title, text, site=None):
    bid, _ = ctx.storage.upsert_bookmark(Bookmark(
        url=url, title=title, date_added=1_700_000_000, browser="T",
        site_name=site))
    if text:
        ctx.storage.conn.execute(
            "UPDATE bookmarks SET page_text=? WHERE id=?", (text, bid))
        ctx.storage.conn.commit()
    return bid


class AutoTagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_tag_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_english_topical_keywords(self):
        text = ("Transformers use attention. Attention lets the model weigh "
                "tokens. Attention and transformers power modern language "
                "models. Tokens flow through attention layers.")
        bid = _bm(self.ctx, "https://ml.example/x", "Attention explained",
                  text, site="ML Blog")
        tags = self.ctx.tagging.auto_tag(bid)
        self.assertIn("ml-blog", tags)                 # source tag from site
        self.assertIn("attention", tags)               # dominant keyword
        self.assertNotIn("the", tags)                  # stopword excluded

    def test_arabic_script_tag(self):
        text = "الذكاء الاصطناعي يغير العالم. الذكاء الاصطناعي مهم جدا للمستقبل."
        bid = _bm(self.ctx, "https://ar.example/x", "الذكاء الاصطناعي", text,
                  site="الجزيرة")
        tags = self.ctx.tagging.auto_tag(bid)
        self.assertIn("arabic", tags)                  # script tag

    def test_cjk_bigrams(self):
        text = "人工知能人工知能技術技術人工知能"  # repeated CJK terms
        bid = _bm(self.ctx, "https://jp.example/x", "人工知能", text)
        tags = self.ctx.tagging.auto_tag(bid)
        self.assertIn("cjk", tags)
        self.assertTrue(any(len(t) == 2 and "\u4e00" <= t[0] <= "\u9fff"
                            for t in tags))            # a CJK bigram keyword

    def test_merge_with_existing_tags(self):
        bid = _bm(self.ctx, "https://x/y", "hello world content here",
                  "content content matters matters here here", site="Site")
        self.ctx.storage.set_tags(bid, ["mine"])
        tags = self.ctx.tagging.auto_tag(bid, merge=True)
        self.assertIn("mine", tags)                    # user tag preserved

    def test_tag_retrieval_round_trip(self):
        bid = _bm(self.ctx, "https://news.example/a", "Elections coverage",
                  "elections elections voting voting results results today",
                  site="News Site")
        tags = self.ctx.tagging.auto_tag(bid)
        # every generated tag can fetch the bookmark back
        for t in tags:
            hits = self.ctx.storage.by_tag(t)
            self.assertTrue(any(h.id == bid for h in hits), f"tag {t!r} lost")

    def test_suggest_does_not_apply(self):
        bid = _bm(self.ctx, "https://x/y", "title", "word word word text text",
                  site="S")
        before = self.ctx.storage.get(bid).tags
        self.ctx.tagging.auto_tag(bid, apply=False)
        self.assertEqual(self.ctx.storage.get(bid).tags, before)  # unchanged


if __name__ == "__main__":
    unittest.main(verbosity=2)
