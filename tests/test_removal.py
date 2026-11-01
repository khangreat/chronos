"""Removal tests: deleting a bookmark removes its archive file and cascades its
snippets/archive row; orphan files get purged; and the core survives — remaining
bookmarks, the schema, and search all keep working.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402

HTML = "<html><head><title>T</title></head><body><article><p>alpha bm25 body</p></article></body></html>"


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_rm_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.a, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://a.test/x", title="A", date_added=1_700_000_000,
            browser="Firefox"))
        self.b, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://b.test/y", title="B", date_added=1_700_003_600,
            browser="Chrome"))
        self.ctx.archive.archive_from_html(self.a, HTML)
        self.snip = self.ctx.snippets.capture(self.a, "alpha bm25 body").id

    def tearDown(self):
        self.ctx.close()

    def test_remove_deletes_file_row_and_snippet(self):
        rec = self.ctx.storage.get_archive(self.a)
        gz = Path(rec["path"])
        self.assertTrue(gz.exists())

        self.ctx.removal.remove_bookmark(self.a)

        self.assertFalse(gz.exists())                         # file gone
        self.assertIsNone(self.ctx.storage.get(self.a))       # bookmark gone
        self.assertIsNone(self.ctx.storage.get_archive(self.a))  # archive row gone
        self.assertIsNone(self.ctx.storage.get_snippet(self.snip))  # snippet cascaded

    def test_core_survives_removal(self):
        self.ctx.removal.remove_bookmark(self.a)
        # the other bookmark, the schema, and search are all intact
        self.assertIsNotNone(self.ctx.storage.get(self.b))
        self.assertEqual(self.ctx.storage.count(), 1)
        self.assertGreaterEqual(self.ctx.storage.version, 5)
        self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://c.test/z", title="gamma", date_added=1_700_010_000,
            browser="Firefox"))
        self.assertTrue(self.ctx.search.search("gamma"))      # index still works

    def test_purge_orphans(self):
        # orphan a file by deleting only the DB row (simulating a lost cascade)
        rec = self.ctx.storage.get_archive(self.a)
        self.ctx.storage.delete_archive(self.a)
        self.assertTrue(Path(rec["path"]).exists())           # file now orphaned
        n = self.ctx.removal.purge_orphans()
        self.assertEqual(n, 1)
        self.assertFalse(Path(rec["path"]).exists())

    def test_remove_many_reports(self):
        r = self.ctx.removal.remove_many([self.a, self.b, 9999])
        self.assertEqual(r.removed, 2)          # 9999 doesn't exist
        self.assertEqual(r.files_deleted, 1)    # only A had an archive
        self.assertEqual(self.ctx.storage.count(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
