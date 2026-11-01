"""Tests for v0.2: extraction (pure function), content storage, CSL-JSON
citations, link provider, and the network gate on fetch. No live network — the
extractor is exercised on a local HTML fixture, which is the correct unit seam.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.config import Config, Settings  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402
from chronos.web.extract import extract_content  # noqa: E402
from chronos.interop import ChronosProvider, bookmark_to_csl  # noqa: E402


SAMPLE_HTML = """<!DOCTYPE html>
<html><head>
  <title>Understanding FTS5 — SQLite Guide</title>
  <meta property="og:site_name" content="SQLite Docs">
  <meta name="author" content="Jane Roe">
  <meta property="article:published_time" content="2024-05-01T09:00:00Z">
  <meta name="description" content="A practical guide to full-text search.">
  <script>var x = 'ignore me';</script>
  <style>.a{color:red}</style>
</head><body>
  <nav>home about ignore</nav>
  <article>
    <h1>Understanding FTS5</h1>
    <p>FTS5 is an SQLite extension for full-text search.</p>
    <p>It ranks results using the bm25 algorithm.</p>
  </article>
  <footer>copyright ignore</footer>
</body></html>"""


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.page = extract_content(SAMPLE_HTML, "https://sqlite.org/fts5.html")

    def test_title_prefers_og_or_title(self):
        self.assertIn("FTS5", self.page.title)

    def test_site_name_from_og(self):
        self.assertEqual(self.page.site_name, "SQLite Docs")

    def test_byline_from_meta(self):
        self.assertEqual(self.page.byline, "Jane Roe")

    def test_published_date_parsed(self):
        from datetime import datetime, timezone
        y = datetime.fromtimestamp(self.page.published_ts, tz=timezone.utc).year
        self.assertEqual(y, 2024)

    def test_body_text_excludes_script_style_nav_footer(self):
        t = self.page.text.lower()
        self.assertIn("bm25", t)
        self.assertNotIn("ignore me", t)   # <script>
        self.assertNotIn("color:red", t)   # <style>
        self.assertNotIn("copyright ignore", t)  # <footer>

    def test_extractor_labelled_builtin(self):
        self.assertEqual(self.page.extractor, "builtin")


class ContentAndInteropTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_v2_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        # Seed a couple of bookmarks directly.
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5 (bookmark title)",
            date_added=1_700_000_000, browser="Firefox"))
        self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://www.youtube.com/watch?v=abc123", title="A talk",
            date_added=1_690_000_000, browser="Firefox"))
        self.ctx.storage.conn.commit()

    def tearDown(self):
        self.ctx.close()

    def test_store_extracted_populates_metadata_and_fts(self):
        page = extract_content(SAMPLE_HTML, "https://sqlite.org/fts5.html")
        self.ctx.content.store_extracted(self.bid, page)
        bm = self.ctx.storage.get(self.bid)
        self.assertEqual(bm.site_name, "SQLite Docs")
        self.assertEqual(bm.byline, "Jane Roe")
        self.assertTrue(bm.has_content)
        # page body now searchable via FTS (bm25 term is only in the body).
        hits = self.ctx.search.search("bm25")
        self.assertTrue(any(h.id == self.bid for h in hits))

    def test_reimport_preserves_fetched_content(self):
        page = extract_content(SAMPLE_HTML, "https://sqlite.org/fts5.html")
        self.ctx.content.store_extracted(self.bid, page)
        # Re-importing the same url must not wipe the extracted content.
        self.ctx.storage.import_bookmarks([Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5 (bookmark title)",
            date_added=1_700_000_000, browser="Firefox")])
        self.assertTrue(self.ctx.storage.get(self.bid).has_content)

    def test_csl_json_shape(self):
        page = extract_content(SAMPLE_HTML, "https://sqlite.org/fts5.html")
        self.ctx.content.store_extracted(self.bid, page)
        csl = self.ctx.provider().resolve_citation("https://sqlite.org/fts5.html")
        self.assertEqual(csl["type"], "webpage")
        self.assertEqual(csl["container-title"], "SQLite Docs")
        self.assertEqual(csl["author"], [{"family": "Roe", "given": "Jane"}])
        self.assertEqual(csl["issued"]["date-parts"][0][0], 2024)
        self.assertIn("accessed", csl)
        self.assertEqual(csl["URL"], "https://sqlite.org/fts5.html")

    def test_citation_works_offline_without_fetch(self):
        # No content stored, network off: still yields a minimal valid citation
        # built from the bookmark itself (title + url + accessed).
        csl = self.ctx.provider().resolve_citation(
            "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(csl["type"], "webpage")
        self.assertEqual(csl["title"], "A talk")
        self.assertIn("accessed", csl)

    def test_citation_unknown_url_returns_none(self):
        self.assertIsNone(
            self.ctx.provider().resolve_citation("https://never.seen/x"))

    def test_link_provider_youtube_filter(self):
        yt = self.ctx.provider().youtube_links()
        self.assertEqual(len(yt), 1)
        self.assertIn("youtube.com/watch", yt[0].url)

    def test_provider_satisfies_protocols(self):
        from chronos.interop import CitationProvider, LinkProvider
        p = self.ctx.provider()
        self.assertIsInstance(p, CitationProvider)
        self.assertIsInstance(p, LinkProvider)

    # -- network gate on fetch --------------------------------------------- #
    def test_fetch_blocked_when_network_off(self):
        with self.assertRaises(NetworkDisabled):
            self.ctx.content.fetch_and_store(self.bid)

    def test_migration_reached_v2(self):
        self.assertGreaterEqual(self.ctx.storage.version, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
