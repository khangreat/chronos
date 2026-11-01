"""Capture tests: kind inference, ingest (resource + manual_capture + quote +
source link + tags), inbox folder ingestion, and the bookmarklet.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.services.capture_service import (  # noqa: E402
    CaptureRecord, bookmarklet, infer_kind)


class InferKindTest(unittest.TestCase):
    def test_x_status(self):
        self.assertEqual(
            infer_kind("https://x.com/user/status/123"), "social_post")

    def test_reddit_post_vs_comment(self):
        self.assertEqual(
            infer_kind("https://www.reddit.com/r/s/comments/ab/slug/"),
            "social_post")
        self.assertEqual(
            infer_kind("https://www.reddit.com/r/s/comments/ab/slug/cid/"),
            "social_comment")

    def test_plain_page(self):
        self.assertEqual(infer_kind("https://dravidology.example/post"), "webpage")

    def test_explicit_wins(self):
        self.assertEqual(infer_kind("https://x/y", "article"), "article")


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_cap_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_ingest_post_with_selection_and_source(self):
        cap = CaptureRecord(
            url="https://x.com/dravidology/status/999",
            title="On Brahui phonology",
            text="A thread about Brahui retroflex consonants and Dravidian roots.",
            selection="Brahui retroflex consonants",
            author="@dravidology",
            source_page="https://x.com/home",
            captured_at=1_700_000_000)
        r = self.ctx.capture.ingest(cap)
        self.assertEqual(r.kind, "social_post")
        self.assertTrue(r.new_resource)
        self.assertTrue(r.quoted)

        bm = self.ctx.storage.get_by_url("https://x.com/dravidology/status/999")
        self.assertEqual(bm.kind, "social_post")
        # manual_capture provenance recorded
        methods = {a["method"] for a in self.ctx.provenance.for_bookmark(bm.id)}
        self.assertIn("manual_capture", methods)
        # selection became a quote
        self.assertEqual(len(self.ctx.snippets.for_bookmark(bm.id)), 1)
        # linked to the page it was found on
        related = [b for _, b in self.ctx.resources.outgoing(bm.id, "related")]
        self.assertEqual(related[0].url, "https://x.com/home")
        # searchable + auto-tagged
        self.assertTrue(self.ctx.search.search("retroflex"))
        self.assertTrue(bm.tags is not None)

    def test_ingest_json_and_explicit_tags(self):
        payload = json.dumps({
            "url": "https://dravidology.example/post-42",
            "title": "Dravidology note", "text": "long form content here",
            "tags": ["dravidology", "linguistics"]})
        r = self.ctx.capture.ingest_json(payload)
        bm = self.ctx.storage.get(r.bookmark_id)
        self.assertIn("dravidology", bm.tags)

    def test_capture_updates_existing_resource_kind(self):
        # a URL already known as a plain bookmark, later captured as a post
        from chronos.core.models import Bookmark
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://x.com/u/status/7", title="x", date_added=1,
            browser="Firefox"))
        self.ctx.capture.ingest(CaptureRecord(url="https://x.com/u/status/7"))
        self.assertEqual(self.ctx.storage.get(bid).kind, "social_post")

    def test_inbox_ingestion(self):
        inbox = self.tmp / "inbox"
        inbox.mkdir()
        for i in range(3):
            (inbox / f"c{i}.chronos.json").write_text(json.dumps(
                {"url": f"https://site.example/p{i}", "title": f"p{i}"}))
        n = self.ctx.capture.ingest_inbox(inbox)
        self.assertEqual(n, 3)
        self.assertEqual(self.ctx.storage.count(), 3)
        # processed files were moved out
        self.assertEqual(len(list(inbox.glob("*.chronos.json"))), 0)
        self.assertEqual(len(list((inbox / "processed").glob("*.json"))), 3)

    def test_bookmarklet_is_wellformed(self):
        b = bookmarklet()
        self.assertTrue(b.startswith("javascript:"))
        self.assertIn("getSelection", b)
        self.assertIn("chronos.json", b)
        self.assertIn("/status/", b)  # best-effort permalink detection


if __name__ == "__main__":
    unittest.main(verbosity=2)
