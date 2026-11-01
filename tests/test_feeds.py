"""Feed tests: RSS 2.0 + Atom parsing (both parser paths), multilingual/RTL
entries, storage as bookmarks, dedupe on refresh, and the network gate.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402
from chronos.feeds.parse import parse_feed, _parse_stdlib  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>The Balochistan Post — Brahui</title>
  <link>https://example.news/</link>
  <item>
    <title>براہوئی خبر ٹیسٹ</title>
    <link>https://example.news/a</link>
    <pubDate>Mon, 03 Feb 2025 08:00:00 +0000</pubDate>
    <description>خبر کا خلاصہ</description>
  </item>
  <item>
    <title>スポーツ ニュース</title>
    <link>https://example.news/b</link>
    <pubDate>Tue, 10 Dec 2024 09:15:00 +0000</pubDate>
    <description>Summary two</description>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Talar Atom</title>
  <link rel="alternate" href="https://talar.example/"/>
  <entry>
    <title>Atom entry one</title>
    <link rel="alternate" href="https://talar.example/1"/>
    <published>2025-01-15T10:00:00Z</published>
    <summary>atom summary</summary>
  </entry>
</feed>"""


class FeedParseTest(unittest.TestCase):
    def test_rss_parse(self):
        r = parse_feed(RSS)
        self.assertEqual(len(r.entries), 2)
        self.assertEqual(r.entries[0].url, "https://example.news/a")
        self.assertIn("Brahui", r.title)

    def test_atom_parse(self):
        r = parse_feed(ATOM)
        self.assertEqual(len(r.entries), 1)
        self.assertEqual(r.entries[0].url, "https://talar.example/1")

    def test_stdlib_fallback_rss(self):
        # Exercise the dependency-free path explicitly.
        r = _parse_stdlib(RSS)
        self.assertEqual(len(r.entries), 2)
        self.assertEqual(r.parser, "stdlib")
        self.assertIsNotNone(r.entries[0].published_ts)

    def test_stdlib_fallback_atom(self):
        r = _parse_stdlib(ATOM)
        self.assertEqual(len(r.entries), 1)
        self.assertEqual(r.entries[0].title, "Atom entry one")


class FeedServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_feed_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_migration_v3_feeds_table(self):
        self.assertGreaterEqual(self.ctx.storage.version, 3)
        self.assertEqual(self.ctx.storage.list_feeds(), [])

    def test_subscribe_stores_entries_as_bookmarks(self):
        r = self.ctx.feeds.subscribe_from_text("https://example.news/feed", RSS)
        self.assertEqual(r.found, 2)
        self.assertEqual(r.new, 2)
        # registered as a feed
        feeds = self.ctx.storage.list_feeds()
        self.assertEqual(len(feeds), 1)
        # entries are normal bookmarks with browser=RSS
        bm = self.ctx.storage.get_by_url("https://example.news/a")
        self.assertEqual(bm.browser, "RSS")
        self.assertEqual(bm.folder_name, "The Balochistan Post — Brahui")
        self.assertEqual((bm.year, bm.month), (2025, 2))

    def test_refresh_is_idempotent(self):
        self.ctx.feeds.subscribe_from_text("https://example.news/feed", RSS)
        r2 = self.ctx.feeds.subscribe_from_text("https://example.news/feed", RSS)
        self.assertEqual(r2.new, 0)  # nothing new on re-pull

    def test_feed_entries_are_searchable_multilingual(self):
        self.ctx.feeds.subscribe_from_text("https://example.news/feed", RSS)
        self.assertTrue(self.ctx.search.search("براہوئی"))   # Brahui RTL
        self.assertTrue(self.ctx.search.search("スポーツ"))    # Japanese

    def test_feed_items_produce_citations(self):
        self.ctx.feeds.subscribe_from_text("https://example.news/feed", RSS)
        csl = self.ctx.provider().resolve_citation("https://example.news/a")
        self.assertEqual(csl["type"], "webpage")
        self.assertEqual(csl["issued"]["date-parts"][0][0], 2025)

    def test_fetch_blocked_when_feeds_capability_off(self):
        with self.assertRaises(NetworkDisabled):
            self.ctx.feeds.subscribe("https://example.news/feed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
