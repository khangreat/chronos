"""Mastodon + Bluesky adapters and the best-ref metadata extractor."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.importers.platform.bluesky import parse_bluesky, at_to_url  # noqa: E402
from chronos.importers.platform.mastodon import parse_outbox  # noqa: E402
from chronos.web.metadata import extract_meta  # noqa: E402

# Mastodon outbox: two Notes, the second replies to the first.
OUTBOX = json.dumps({
    "type": "OrderedCollection",
    "orderedItems": [
        {"type": "Create", "object": {
            "type": "Note", "id": "https://m.social/users/x/statuses/1",
            "url": "https://m.social/@x/1", "content": "<p>Root about Brahui</p>",
            "published": "2024-01-01T10:00:00Z",
            "attributedTo": "https://m.social/users/x"}},
        {"type": "Create", "object": {
            "type": "Note", "id": "https://m.social/users/x/statuses/2",
            "url": "https://m.social/@x/2", "content": "<p>A reply</p>",
            "published": "2024-01-01T10:05:00Z",
            "inReplyTo": "https://m.social/users/x/statuses/1",
            "attributedTo": "https://m.social/users/x"}},
        {"type": "Announce", "object": "https://other/1"}  # a boost, ignored
    ]})

# Bluesky listRecords shape, second post replies to the first.
BSKY = json.dumps({"records": [
    {"uri": "at://did:plc:abc/app.bsky.feed.post/aaa",
     "value": {"text": "Bluesky root", "createdAt": "2024-02-01T09:00:00Z"}},
    {"uri": "at://did:plc:abc/app.bsky.feed.post/bbb",
     "value": {"text": "bsky reply", "createdAt": "2024-02-01T09:01:00Z",
               "reply": {"parent": {"uri": "at://did:plc:abc/app.bsky.feed.post/aaa"}}}},
]})

HTML_META = """<html><head>
<title>Fallback Title</title>
<meta property="og:title" content="A Great Article">
<meta property="og:site_name" content="Example News">
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2023-05-04T08:00:00Z">
<meta property="og:description" content="A short summary of the piece.">
<script type="application/ld+json">{"@type":"Article","headline":"LD head",
"author":{"name":"LD Author"},"datePublished":"2023-05-04"}</script>
</head><body>...</body></html>"""


class ParseTest(unittest.TestCase):
    def test_mastodon_outbox(self):
        posts = parse_outbox(OUTBOX)
        self.assertEqual(len(posts), 2)          # boost ignored
        self.assertEqual(posts[0].text, "Root about Brahui")
        self.assertEqual(posts[0].author, "@x@m.social")
        self.assertEqual(posts[1].in_reply_to,
                         "https://m.social/users/x/statuses/1")

    def test_bluesky_url_and_reply(self):
        posts = parse_bluesky(BSKY)
        self.assertEqual(posts[0].url,
                         "https://bsky.app/profile/did:plc:abc/post/aaa")
        self.assertEqual(posts[1].reply_parent_uri,
                         "at://did:plc:abc/app.bsky.feed.post/aaa")

    def test_at_to_url(self):
        self.assertEqual(
            at_to_url("at://did:plc:z/app.bsky.feed.post/xyz", "alice.bsky.social"),
            "https://bsky.app/profile/alice.bsky.social/post/xyz")

    def test_metadata_prefers_og_then_jsonld(self):
        m = extract_meta(HTML_META)
        self.assertEqual(m["title"], "A Great Article")   # og over <title>
        self.assertEqual(m["author"], "Jane Doe")         # meta author
        self.assertEqual(m["site_name"], "Example News")
        self.assertIn("published_ts", m)


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_soc_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _f(self, text, name):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_mastodon_import_threads_and_author(self):
        r = self.ctx.platform_import.import_mastodon(self._f(OUTBOX, "outbox.json"))
        self.assertEqual(r.resources, 2)
        self.assertEqual(len(self.ctx.resources.by_kind("social_post")), 2)
        root = self.ctx.storage.get_by_url("https://m.social/@x/1")
        reply = self.ctx.storage.get_by_url("https://m.social/@x/2")
        self.assertEqual(root.byline, "@x@m.social")
        self.assertEqual(self.ctx.resources.parent(reply.id).id, root.id)
        self.assertTrue(self.ctx.search.search("Brahui"))

    def test_bluesky_import_threads(self):
        r = self.ctx.platform_import.import_bluesky(self._f(BSKY, "bsky.json"))
        self.assertEqual(r.resources, 2)
        root = self.ctx.storage.get_by_url(
            "https://bsky.app/profile/did:plc:abc/post/aaa")
        reply = self.ctx.storage.get_by_url(
            "https://bsky.app/profile/did:plc:abc/post/bbb")
        self.assertEqual(self.ctx.resources.parent(reply.id).id, root.id)

    def test_archive_enriches_best_ref(self):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://ex.example/a", title="x", date_added=1, browser="F"))
        self.ctx.archive.archive_from_html(bid, HTML_META, "https://ex.example/a")
        bm = self.ctx.storage.get(bid)
        self.assertEqual(bm.byline, "Jane Doe")       # filled from metadata
        self.assertEqual(bm.site_name, "Example News")
        self.assertIsNotNone(bm.published_ts)

    def test_reimport_mastodon_noop(self):
        f = self._f(OUTBOX, "outbox.json")
        self.ctx.platform_import.import_mastodon(f)
        r2 = self.ctx.platform_import.import_mastodon(f)
        self.assertTrue(r2.already_imported)
        self.assertEqual(len(self.ctx.resources.by_kind("social_post")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
