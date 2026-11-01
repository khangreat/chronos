"""X (Twitter) archive import tests: JS-wrapper parsing, tweets → typed
resources with thread relationships, likes → platform_liked acquisitions,
provenance + package, and incremental re-import.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.importers.platform.twitter import parse_tweets, parse_likes  # noqa: E402

# A self-thread: tweet 2 replies to tweet 1; tweet 3 is standalone.
TWEETS_JS = """window.YTD.tweets.part0 = [
  {"tweet": {"id_str": "1001", "full_text": "First tweet in a thread about Brahui",
             "created_at": "Wed Oct 10 20:19:24 +0000 2018"}},
  {"tweet": {"id_str": "1002", "full_text": "Second tweet continuing the thread",
             "created_at": "Wed Oct 10 20:25:00 +0000 2018",
             "in_reply_to_status_id_str": "1001"}},
  {"tweet": {"id_str": "1003", "full_text": "An unrelated standalone tweet",
             "created_at": "Thu Oct 11 09:00:00 +0000 2018"}}
];"""

LIKE_JS = """window.YTD.like.part0 = [
  {"like": {"tweetId": "2001", "fullText": "A liked tweet",
            "expandedUrl": "https://twitter.com/someone/status/2001"}}
];"""


class XParseTest(unittest.TestCase):
    def test_parse_tweets_wrapper_and_reply(self):
        recs = parse_tweets(TWEETS_JS)
        self.assertEqual(len(recs), 3)
        self.assertTrue(recs[0].url.endswith("/1001"))
        self.assertIsNotNone(recs[0].created_ts)
        self.assertEqual(recs[1].in_reply_to, "1001")

    def test_parse_likes(self):
        recs = parse_likes(LIKE_JS)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].url,
                         "https://twitter.com/someone/status/2001")

    def test_bad_js_returns_empty(self):
        self.assertEqual(parse_tweets("not valid at all"), [])


class XImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_x_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _f(self, text, name):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_tweets_import_types_and_threads(self):
        r = self.ctx.platform_import.import_x_tweets(self._f(TWEETS_JS, "tweets.js"))
        self.assertEqual(r.resources, 3)
        self.assertEqual(r.new_resources, 3)
        # all three are social posts
        self.assertEqual(len(self.ctx.resources.by_kind("social_post")), 3)
        # the thread reply is linked
        t1 = self.ctx.storage.get_by_url("https://twitter.com/i/web/status/1001")
        t2 = self.ctx.storage.get_by_url("https://twitter.com/i/web/status/1002")
        self.assertEqual(self.ctx.resources.parent(t2.id).id, t1.id)
        self.assertEqual([b.id for b in self.ctx.resources.replies(t1.id)], [t2.id])
        # provenance: imported from x
        self.assertEqual(len(self.ctx.provenance.by_source("x")), 3)

    def test_tweet_content_searchable(self):
        self.ctx.platform_import.import_x_tweets(self._f(TWEETS_JS, "tweets.js"))
        self.assertTrue(self.ctx.search.search("Brahui"))

    def test_likes_import_records_platform_liked(self):
        r = self.ctx.platform_import.import_x_likes(self._f(LIKE_JS, "like.js"))
        self.assertEqual(r.new_resources, 1)
        self.assertEqual(len(self.ctx.provenance.by_method("platform_liked")), 1)

    def test_reimport_same_file_noop(self):
        f = self._f(TWEETS_JS, "tweets.js")
        self.ctx.platform_import.import_x_tweets(f)
        r2 = self.ctx.platform_import.import_x_tweets(f)
        self.assertTrue(r2.already_imported)
        self.assertEqual(len(self.ctx.provenance.packages()), 1)
        self.assertEqual(len(self.ctx.resources.by_kind("social_post")), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
