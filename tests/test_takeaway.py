"""Takeaway tests: authored distillations distinct from quotes/notes, surviving
dedupe/merge (reassigned to survivor) and removed only on delete.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402


class TakeawayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_tk_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _bm(self, url):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=url, title="t", date_added=1, browser="F"))
        return bid

    def test_migration_v8(self):
        self.assertGreaterEqual(self.ctx.storage.version, 8)

    def test_add_list_update_remove(self):
        bid = self._bm("https://x/1")
        tid = self.ctx.takeaways.add(bid, "the point is X")
        got = self.ctx.takeaways.for_bookmark(bid)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].text, "the point is X")
        self.ctx.takeaways.update(tid, "the point is Y")
        self.assertEqual(self.ctx.takeaways.for_bookmark(bid)[0].text,
                         "the point is Y")
        self.ctx.takeaways.remove(tid)
        self.assertEqual(self.ctx.takeaways.for_bookmark(bid), [])

    def test_empty_text_rejected(self):
        bid = self._bm("https://x/2")
        with self.assertRaises(ValueError):
            self.ctx.takeaways.add(bid, "   ")

    def test_distinct_from_quotes(self):
        bid = self._bm("https://x/3")
        self.ctx.takeaways.add(bid, "my distilled point")
        self.ctx.snippets.capture(bid, "the source's exact words")
        # they live in separate stores
        self.assertEqual(len(self.ctx.takeaways.for_bookmark(bid)), 1)
        self.assertEqual(len(self.ctx.snippets.for_bookmark(bid)), 1)

    def test_survives_dedupe_merge(self):
        a = self._bm("https://site.example/x")
        # a duplicate that will be merged into the canonical
        b, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://www.site.example/x/", title="dup", date_added=1,
            browser="F"))
        self.ctx.takeaways.add(b, "keep me through the merge")
        self.ctx.curation.merge_all()
        # the takeaway was reassigned to the surviving resource, not lost
        survivors = [t["text"] for t in self.ctx.storage.all_takeaways()]
        self.assertIn("keep me through the merge", survivors)
        self.assertEqual(len(self.ctx.storage.all_takeaways()), 1)

    def test_removed_with_resource(self):
        bid = self._bm("https://x/4")
        self.ctx.takeaways.add(bid, "gone when the resource goes")
        self.ctx.removal.remove_many([bid])
        self.assertEqual(self.ctx.storage.all_takeaways(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
