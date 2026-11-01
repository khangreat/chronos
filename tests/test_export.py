"""Export + curation tests. Where possible, parse the output back (round-trip)
rather than eyeballing strings.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.export import exporters as X  # noqa: E402
from chronos.services.curation_service import normalize_url  # noqa: E402
from chronos.importers.html_import import HTMLImporter  # noqa: E402
from chronos.feeds.parse import parse_feed  # noqa: E402


def _seed(ctx):
    bms = [
        Bookmark(url="https://sqlite.org/fts5.html", title="FTS5",
                 date_added=1_704_067_200, browser="Firefox",
                 site_name="SQLite Docs", byline="Jane Roe",
                 published_ts=1_714_550_400, tags=["db", "search"]),
        Bookmark(url="https://ar.example/مقالة", title="مقالة عربية",
                 date_added=1_700_000_000, browser="Chrome"),
        Bookmark(url="https://docs.python.org", title="Python",
                 date_added=1_690_000_000, browser="Firefox"),
    ]
    ctx.storage.import_bookmarks(bms)


class ExportFormatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_exp_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        _seed(self.ctx)
        self.bms = self.ctx.storage.all_bookmarks()

    def tearDown(self):
        self.ctx.close()

    def test_csl_json_valid_array(self):
        data = json.loads(self.ctx.export.export("csl"))
        self.assertEqual(len(data), 3)
        self.assertTrue(all(d["type"] == "webpage" for d in data))

    def test_bibtex_has_online_entries(self):
        out = self.ctx.export.export("bibtex")
        self.assertEqual(out.count("@online{"), 3)
        self.assertIn("url = {https://sqlite.org/fts5.html}", out)

    def test_ris_records(self):
        out = self.ctx.export.export("ris")
        self.assertEqual(out.count("TY  - ELEC"), 3)
        self.assertEqual(out.count("ER  - "), 3)

    def test_netscape_html_roundtrips_through_importer(self):
        html = self.ctx.export.export("html")
        p = self.tmp / "out.html"
        p.write_text(html, encoding="utf-8")
        reimported = HTMLImporter().parse(p)
        urls_in = {b.url for b in self.bms}
        urls_out = {b.url for b in reimported}
        self.assertEqual(urls_in, urls_out)  # every bookmark survives the round-trip

    def test_json_and_csv_parse(self):
        data = json.loads(self.ctx.export.export("json"))
        self.assertEqual(len(data), 3)
        csv_text = self.ctx.export.export("csv")
        self.assertEqual(csv_text.count("\n"), 4)  # header + 3 rows

    def test_opml_roundtrip(self):
        self.ctx.storage.add_feed("https://f.test/rss", "My Feed", "https://f.test")
        opml = self.ctx.export.export("opml")
        ET.fromstring(opml)  # valid XML
        parsed = X.opml_to_feed_urls(opml)
        self.assertEqual(parsed[0]["url"], "https://f.test/rss")


class QuoteExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_qexp_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5",
            date_added=1_704_067_200, browser="Firefox",
            site_name="SQLite Docs", published_ts=1_714_550_400))
        self.ctx.snippets.capture(bid, "bm25 ranks results.", note="key",
                                  locator="para 1")
        self.ctx.snippets.capture(bid, "براہوئی اقتباس")  # RTL quote

    def tearDown(self):
        self.ctx.close()

    def test_web_annotations_shape(self):
        anns = json.loads(self.ctx.export.export("annotations"))
        self.assertEqual(len(anns), 2)
        a = anns[0]
        self.assertEqual(a["type"], "Annotation")
        self.assertEqual(a["target"]["selector"]["type"], "TextQuoteSelector")
        self.assertEqual(a["target"]["selector"]["exact"], "bm25 ranks results.")
        self.assertEqual(a["target"]["source"], "https://sqlite.org/fts5.html")

    def test_web_annotation_marks_rtl(self):
        anns = json.loads(self.ctx.export.export("annotations"))
        rtl = [a for a in anns if a.get("textDirection") == "rtl"]
        self.assertEqual(len(rtl), 1)

    def test_quotes_markdown(self):
        md = self.ctx.export.export("quotes-md")
        self.assertIn("> bm25 ranks results. (para 1)", md)
        self.assertIn("SQLite Docs", md)


class CurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_cur_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_normalize_url(self):
        self.assertEqual(normalize_url("https://WWW.Example.com/a/"),
                         normalize_url("https://example.com/a"))

    def test_find_and_merge_duplicates_preserves_data(self):
        # same page in two browsers (+ www / trailing slash variance)
        b1, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.com/a", title="A", date_added=1_700_000_000,
            browser="Firefox", notes="note1"))
        self.ctx.storage.set_tags(b1, ["keep"])
        b2, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://www.example.com/a/", title="A dup",
            date_added=1_700_000_000, browser="Chrome", is_favorite=True))
        sid = self.ctx.snippets.capture(b2, "quote from dup").id

        groups = self.ctx.curation.find_duplicate_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

        r = self.ctx.curation.merge_all()
        self.assertEqual(r.removed, 1)
        self.assertEqual(self.ctx.storage.count(), 1)  # one canonical remains

        # surviving record kept the tag, favourite, both notes, and the snippet
        surv = self.ctx.storage.all_bookmarks()[0]
        self.assertIn("keep", surv.tags)
        self.assertTrue(surv.is_favorite)
        snip = self.ctx.storage.get_snippet(sid)
        self.assertIsNotNone(snip)                    # snippet not lost
        self.assertEqual(snip.bookmark_id, surv.id)   # reassigned to canonical


if __name__ == "__main__":
    unittest.main(verbosity=2)
