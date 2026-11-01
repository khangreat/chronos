"""Archive tests: offline snapshot from HTML round-trips through gzip, stores
extracted text + search, records the archive, and the fetch path is gated.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402

HTML = ("<html><head><title>Archived page</title>"
        "<meta property='og:site_name' content='Example News'></head>"
        "<body><nav>menu</nav><article><h1>Headline</h1>"
        "<p>The body text mentions bm25 and stays offline.</p></article>"
        "<footer>ads</footer></body></html>")


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_arch_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.news/a", title="A", date_added=1_700_000_000,
            browser="Firefox"))

    def tearDown(self):
        self.ctx.close()

    def test_migration_v5(self):
        self.assertGreaterEqual(self.ctx.storage.version, 5)
        self.assertEqual(self.ctx.storage.archive_count(), 0)

    def test_archive_from_html_roundtrips(self):
        r = self.ctx.archive.archive_from_html(self.bid, HTML)
        self.assertGreater(r.bytes, 0)
        self.assertTrue(Path(r.path).exists())
        self.assertTrue(self.ctx.archive.has_archive(self.bid))
        # gzip round-trip returns the exact HTML
        self.assertEqual(self.ctx.archive.read_html(self.bid), HTML)

    def test_archive_stores_extracted_text_and_search(self):
        self.ctx.archive.archive_from_html(self.bid, HTML)
        bm = self.ctx.storage.get(self.bid)
        self.assertTrue(bm.has_content)
        self.assertEqual(bm.site_name, "Example News")
        self.assertTrue(any(h.id == self.bid
                            for h in self.ctx.search.search("bm25")))

    def test_rearchive_updates_not_duplicates(self):
        self.ctx.archive.archive_from_html(self.bid, HTML)
        self.ctx.archive.archive_from_html(self.bid, HTML + "<!-- v2 -->")
        self.assertEqual(self.ctx.storage.archive_count(), 1)  # UNIQUE bookmark_id

    def test_deleting_bookmark_cascades_archive_row(self):
        self.ctx.archive.archive_from_html(self.bid, HTML)
        self.ctx.storage.delete_bookmark(self.bid)
        self.assertIsNone(self.ctx.storage.get_archive(self.bid))

    def test_network_archive_gated(self):
        with self.assertRaises(NetworkDisabled):
            self.ctx.archive.archive(self.bid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
