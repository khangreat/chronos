"""Resource kind + relationship tests: kinds set/queried, relationship graph,
Reddit posts/comments get typed and comments link reply_to their submission.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402

RSS = ("<?xml version='1.0'?><rss version='2.0'><channel><title>F</title>"
       "<link>https://s/</link><item><title>hi</title><link>https://s/a</link>"
       "<pubDate>Mon, 03 Feb 2025 08:00:00 +0000</pubDate></item></channel></rss>")

POSTS = ("id,permalink\n"
         "t3_x,https://www.reddit.com/r/python/comments/xxxx/cool_thing/\n")
COMMENTS = ("id,permalink\n"
            "t1_c,https://www.reddit.com/r/python/comments/xxxx/cool_thing/ccc/\n")


class ResourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_res_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _write(self, text, name):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_migration_v7_and_default_kind(self):
        self.assertGreaterEqual(self.ctx.storage.version, 7)
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x/y", title="x", date_added=1, browser="F"))
        self.assertEqual(self.ctx.storage.get(bid).kind, "webpage")

    def test_set_kind_and_by_kind(self):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x/y", title="x", date_added=1, browser="F"))
        self.ctx.resources.set_kind(bid, "article")
        self.assertEqual(self.ctx.storage.get(bid).kind, "article")
        self.assertEqual(len(self.ctx.resources.by_kind("article")), 1)
        with self.assertRaises(ValueError):
            self.ctx.resources.set_kind(bid, "nonsense")

    def test_relationship_graph(self):
        a, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x/a", title="a", date_added=1, browser="F"))
        b, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x/b", title="b", date_added=1, browser="F"))
        self.ctx.resources.relate(a, b, "quotes")
        self.assertEqual(self.ctx.resources.outgoing(a)[0][0], "quotes")
        self.assertEqual(self.ctx.resources.incoming(b)[0][1].id, a)
        with self.assertRaises(ValueError):
            self.ctx.resources.relate(a, b, "bogus")
        with self.assertRaises(ValueError):
            self.ctx.resources.relate(a, a, "related")

    def test_feed_items_are_feed_entry_kind(self):
        self.ctx.feeds.subscribe_from_text("https://s/feed", RSS)
        bm = self.ctx.storage.get_by_url("https://s/a")
        self.assertEqual(bm.kind, "feed_entry")

    def test_reddit_posts_and_comments_typed_and_linked(self):
        self.ctx.platform_import.import_reddit_csv(
            self._write(POSTS, "saved_posts.csv"), kind="post")
        self.ctx.platform_import.import_reddit_csv(
            self._write(COMMENTS, "saved_comments.csv"), kind="comment")

        post = self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/python/comments/xxxx/cool_thing/")
        comment = self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/python/comments/xxxx/cool_thing/ccc/")
        self.assertEqual(post.kind, "social_post")
        self.assertEqual(comment.kind, "social_comment")

        # the comment replies_to the submission; the post lists it as a reply
        self.assertEqual(self.ctx.resources.parent(comment.id).id, post.id)
        replies = self.ctx.resources.replies(post.id)
        self.assertEqual([r.id for r in replies], [comment.id])

    def test_by_kind_counts(self):
        self.ctx.platform_import.import_reddit_csv(
            self._write(POSTS, "saved_posts.csv"), kind="post")
        self.assertEqual(len(self.ctx.resources.by_kind("social_post")), 1)
        self.assertEqual(len(self.ctx.resources.by_kind("social_comment")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
