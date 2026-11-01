"""Provenance tests: acquisitions recorded on the live import paths, multiple
acquisitions per resource, method/source queries, and the Reddit platform
importer (DataPackage + resources + platform_saved, incremental re-import).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from tests.fixtures import build_netscape_html  # noqa: E402

REDDIT_POSTS = (
    "id,permalink\n"
    "t3_abc,https://www.reddit.com/r/python/comments/abc/cool_python_thing/\n"
    "t3_def,/r/rust/comments/def/a_rust_post/\n"
    "t3_ghi,https://www.reddit.com/r/brahui/comments/ghi/language_note/\n"
)
REDDIT_POSTS_V2 = REDDIT_POSTS + (
    "t3_jkl,https://www.reddit.com/r/python/comments/jkl/newer_saved/\n")


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_prov_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _reddit(self, text, name="saved_posts.csv"):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_migration_v6(self):
        self.assertGreaterEqual(self.ctx.storage.version, 6)

    def test_html_import_records_acquisition(self):
        build_netscape_html(self.tmp / "bm.html")
        self.ctx.bookmarks.import_html(self.tmp / "bm.html")
        b = self.ctx.storage.all_bookmarks()[0]
        acqs = self.ctx.provenance.for_bookmark(b.id)
        self.assertTrue(acqs)
        self.assertEqual(acqs[0]["method"], "imported")

    def test_reddit_import_full_flow(self):
        r = self.ctx.platform_import.import_reddit_csv(self._reddit(REDDIT_POSTS))
        self.assertFalse(r.already_imported)
        self.assertEqual(r.resources, 3)
        self.assertEqual(r.new_resources, 3)
        self.assertEqual(r.acquisitions, 3)
        # a package was recorded with the file hash + entity count
        pkgs = self.ctx.provenance.packages()
        self.assertEqual(len(pkgs), 1)
        self.assertEqual(pkgs[0]["provider"], "reddit")
        self.assertEqual(pkgs[0]["entity_count"], 3)
        # resources are queryable by acquisition method + source
        saved = self.ctx.provenance.by_method("platform_saved")
        self.assertEqual(len(saved), 3)
        self.assertEqual(len(self.ctx.provenance.by_source("reddit")), 3)
        # the relative permalink was resolved to a full URL
        self.assertIsNotNone(
            self.ctx.storage.get_by_url(
                "https://www.reddit.com/r/rust/comments/def/a_rust_post/"))

    def test_reimport_same_file_is_noop(self):
        f = self._reddit(REDDIT_POSTS)
        self.ctx.platform_import.import_reddit_csv(f)
        r2 = self.ctx.platform_import.import_reddit_csv(f)
        self.assertTrue(r2.already_imported)
        self.assertEqual(len(self.ctx.provenance.packages()), 1)  # same hash
        self.assertEqual(len(self.ctx.provenance.by_method("platform_saved")), 3)

    def test_newer_export_adds_occurrence_not_duplicates(self):
        self.ctx.platform_import.import_reddit_csv(self._reddit(REDDIT_POSTS))
        # a newer export (different content -> different hash) with one new item
        r2 = self.ctx.platform_import.import_reddit_csv(
            self._reddit(REDDIT_POSTS_V2, name="saved_posts_2.csv"))
        self.assertFalse(r2.already_imported)
        self.assertEqual(len(self.ctx.provenance.packages()), 2)     # two exports
        self.assertEqual(r2.new_resources, 1)                        # only 1 new
        # the 3 persisting resources each gained a second acquisition occurrence
        url = "https://www.reddit.com/r/python/comments/abc/cool_python_thing/"
        b = self.ctx.storage.get_by_url(url)
        self.assertEqual(len(self.ctx.provenance.for_bookmark(b.id)), 2)

    def test_multiple_acquisitions_per_resource(self):
        # same URL arrives via HTML import AND a reddit export -> one resource,
        # two acquisitions of different methods.
        url = "https://www.reddit.com/r/python/comments/abc/cool_python_thing/"
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=url, title="x", date_added=1, browser="Firefox"))
        self.ctx.storage.add_acquisition(bid, "browser_bookmark", "firefox")
        self.ctx.platform_import.import_reddit_csv(self._reddit(REDDIT_POSTS))
        methods = {a["method"] for a in self.ctx.provenance.for_bookmark(bid)}
        self.assertEqual(methods, {"browser_bookmark", "platform_saved"})

    def test_record_validates_method_and_is_idempotent(self):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x/y", title="x", date_added=1, browser="F"))
        with self.assertRaises(ValueError):
            self.ctx.provenance.record(bid, "not_a_method")
        first = self.ctx.provenance.record(bid, "manual_capture", "reader")
        again = self.ctx.provenance.record(bid, "manual_capture", "reader")
        self.assertIsNotNone(first)
        self.assertIsNone(again)  # idempotent


if __name__ == "__main__":
    unittest.main(verbosity=2)
