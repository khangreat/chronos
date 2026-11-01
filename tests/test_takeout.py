"""Takeout tests: inventory + ownership classification, ingest of Chronos-owned
parts with provenance, handoff manifests for other apps, and incremental
re-import.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.importers.platform.takeout import inspect_takeout  # noqa: E402

BOOKMARKS_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><A HREF="https://dravidology.example/a" ADD_DATE="1700000000">Dravidology A</A>
<DT><A HREF="https://brahui.example/b" ADD_DATE="1700000001">Brahui B</A>
</DL><p>"""


def _make_takeout(path: Path) -> Path:
    """A small but realistic Takeout zip spanning several owners."""
    zpath = path / "takeout.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("Takeout/Chrome/Bookmarks.html", BOOKMARKS_HTML)
        z.writestr("Takeout/Chrome/History.json", '{"Browser History": []}')
        z.writestr("Takeout/YouTube and YouTube Music/subscriptions/subs.csv",
                   "Channel Id,Channel Url,Channel Title\nabc,https://x,Chan")
        z.writestr("Takeout/Calendar/My Calendar.ics", "BEGIN:VCALENDAR\nEND:VCALENDAR")
        z.writestr("Takeout/Keep/note1.json", '{"title":"a note"}')
        z.writestr("Takeout/Drive/file.txt", "ignore me")
    return zpath


class InspectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_tk_"))
        self.zip = _make_takeout(self.tmp)

    def test_classification(self):
        plan = inspect_takeout(self.zip)
        owner = {c.product: c.owner for c in plan.categories}
        self.assertEqual(owner["Chrome"], "chronos")
        self.assertEqual(owner["YouTube and YouTube Music"], "ytman")
        self.assertEqual(owner["Calendar"], "cc")
        self.assertEqual(owner["Keep"], "nawishtar")
        self.assertEqual(owner["Drive"], "skip")

    def test_summary_counts(self):
        plan = inspect_takeout(self.zip)
        s = plan.summary()
        self.assertEqual(s["chronos"], 1)
        self.assertEqual(s["ytman"], 1)
        self.assertEqual(s["cc"], 1)

    def test_folder_form(self):
        # inspecting an extracted folder works the same as the zip
        folder = self.tmp / "extracted"
        with zipfile.ZipFile(self.zip) as z:
            z.extractall(folder)
        plan = inspect_takeout(folder)
        owners = {c.owner for c in plan.categories}
        self.assertIn("chronos", owners)
        self.assertIn("ytman", owners)


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_tki_"))
        self.zip = _make_takeout(self.tmp)
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_import_ingests_bookmarks_with_provenance(self):
        r = self.ctx.takeout.import_takeout(self.zip)
        self.assertFalse(r.already_imported)
        self.assertEqual(r.ingested_bookmarks, 2)
        bm = self.ctx.storage.get_by_url("https://dravidology.example/a")
        self.assertIsNotNone(bm)
        acqs = self.ctx.provenance.for_bookmark(bm.id)
        self.assertEqual(acqs[0]["method"], "imported")
        self.assertEqual(acqs[0]["source"], "google_takeout")
        # a data package was recorded and links the acquisition
        self.assertEqual(len(self.ctx.provenance.packages()), 1)
        self.assertIsNotNone(acqs[0]["package_id"])

    def test_handoffs_written_for_other_owners(self):
        r = self.ctx.takeout.import_takeout(self.zip)
        self.assertIn("ytman", r.handoffs)
        self.assertIn("cc", r.handoffs)
        self.assertIn("nawishtar", r.handoffs)
        # the ytman manifest names the YouTube category + its files
        y = json.loads(Path(r.handoffs["ytman"]).read_text(encoding="utf-8"))
        self.assertEqual(y["target"], "ytman")
        self.assertEqual(y["package_hash"][:0], "")  # present
        self.assertTrue(any("YouTube" in c["product"] for c in y["categories"]))

    def test_reimport_same_takeout_noop(self):
        self.ctx.takeout.import_takeout(self.zip)
        r2 = self.ctx.takeout.import_takeout(self.zip)
        self.assertTrue(r2.already_imported)
        self.assertEqual(self.ctx.storage.count(), 2)  # no duplicate resources
        self.assertEqual(len(self.ctx.provenance.packages()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
