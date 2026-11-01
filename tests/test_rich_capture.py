"""Rich-capture tests: a live capture carrying page metadata yields a resource
with a full best-ref (author/site/date/description) and therefore a complete CSL
citation. Front-ends (bookmarklet + extension) read that metadata from the DOM.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.interop import ChronosProvider  # noqa: E402
from chronos.services.capture_service import (  # noqa: E402
    CaptureRecord, bookmarklet)


class RichCaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_rc_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _cap(self):
        return CaptureRecord(
            url="https://m.social/@dravidology/9",
            title="On Brahui", text="A post about Brahui phonology.",
            author="@dravidology@m.social", site_name="m.social",
            description="Notes on retroflex consonants.",
            published="2024-03-01T12:00:00Z", kind="social_post")

    def test_capture_sets_best_ref_fields(self):
        r = self.ctx.capture.ingest(self._cap())
        bm = self.ctx.storage.get(r.bookmark_id)
        self.assertEqual(bm.byline, "@dravidology@m.social")
        self.assertEqual(bm.site_name, "m.social")
        self.assertIsNotNone(bm.published_ts)          # ISO parsed to epoch
        self.assertEqual(bm.excerpt, "Notes on retroflex consonants.")

    def test_emitted_csl_is_complete(self):
        r = self.ctx.capture.ingest(self._cap())
        ref = ChronosProvider(self.ctx).get_resource(
            "https://m.social/@dravidology/9")
        csl = ref["csl"]
        self.assertEqual(csl["type"], "post")
        self.assertEqual(csl["author"][0]["literal"], "@dravidology@m.social")
        self.assertEqual(csl["container-title"], "m.social")
        self.assertIn("issued", csl)                   # publish date present

    def test_recapture_fills_missing_only(self):
        # first capture has no author; a later one supplies it
        self.ctx.capture.ingest(CaptureRecord(url="https://ex/1", title="t"))
        self.ctx.capture.ingest(CaptureRecord(
            url="https://ex/1", author="Jane Doe", site_name="Ex"))
        bm = self.ctx.storage.get_by_url("https://ex/1")
        self.assertEqual(bm.byline, "Jane Doe")

    def test_published_epoch_string_accepted(self):
        self.ctx.capture.ingest(CaptureRecord(
            url="https://ex/2", published="1700000000"))
        self.assertEqual(self.ctx.storage.get_by_url("https://ex/2").published_ts,
                         1700000000)

    def test_frontends_read_metadata(self):
        b = bookmarklet()
        self.assertIn("og:site_name", b)
        self.assertIn("article:published_time", b)
        ext = (Path(__file__).resolve().parents[1] /
               "chronos/extension/webext/background.js").read_text(encoding="utf-8")
        self.assertIn("application/ld+json", ext)      # JSON-LD read in-page
        self.assertIn("og:site_name", ext)


if __name__ == "__main__":
    unittest.main(verbosity=2)
