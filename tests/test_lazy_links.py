"""v0.10 tests: lazy keyset paging (completeness + no dupes), dead-link
detection against a local server, and Wayback availability parsing.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.config import Config, Settings  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class LazyModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_lazy_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        # 500 bookmarks in 2024, in tie-groups of 7 sharing a timestamp — this
        # is what makes the (date_added, id) keyset tiebreak necessary at seams.
        base = 1_704_067_200
        self.ctx.storage.import_bookmarks([
            Bookmark(url=f"https://e.test/{i}", title=f"Item {i}",
                     date_added=base + (i // 7) * 3600, browser="Firefox")
            for i in range(500)])

    def tearDown(self):
        self.ctx.close()

    def test_first_page_then_fetch_more_to_completion(self):
        from chronos.gui.stream_model import BookmarkListModel, ENTRY_ROLE
        m = BookmarkListModel()
        m.set_period(self.ctx.storage, 2024, 0)
        # first page only
        self.assertEqual(m.item_count(), 200)
        self.assertTrue(m.canFetchMore())
        # page in the rest
        guard = 0
        while m.canFetchMore() and guard < 20:
            m.fetchMore()
            guard += 1
        self.assertFalse(m.canFetchMore())
        self.assertEqual(m.item_count(), 500)

    def test_keyset_paging_is_complete_and_unique(self):
        from chronos.gui.stream_model import BookmarkListModel, ENTRY_ROLE
        m = BookmarkListModel()
        m.set_period(self.ctx.storage, 2024, 0)
        while m.canFetchMore():
            m.fetchMore()
        ids = [m.data(m.index(r), ENTRY_ROLE).bookmark.id
               for r in range(m.rowCount())
               if m.data(m.index(r), ENTRY_ROLE).kind == "item"]
        self.assertEqual(len(ids), 500)          # nothing dropped
        self.assertEqual(len(set(ids)), 500)     # nothing duplicated at page seams


class LinkServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_link_"))
        cfg = Config(self.tmp / "home")
        cfg.save_settings(Settings(network_enabled=True, allow_link_check=True,
                                    allow_private_addresses=True))  # local test server
        self.ctx = ApplicationContext(cfg)

        class H(http.server.BaseHTTPRequestHandler):
            def _route(self):
                code = 200 if self.path == "/ok" else 404
                self.send_response(code); self.end_headers()

            do_HEAD = _route
            do_GET = _route

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ok, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=f"http://127.0.0.1:{self.port}/ok", title="ok",
            date_added=1_700_000_000, browser="Firefox"))
        self.gone, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=f"http://127.0.0.1:{self.port}/gone", title="gone",
            date_added=1_700_000_000, browser="Firefox"))

    def tearDown(self):
        self.server.shutdown()
        self.ctx.close()

    def test_marks_dead_and_alive(self):
        r = self.ctx.links.check_all(use_wayback=False)
        self.assertEqual(r.checked, 2)
        self.assertEqual(r.dead, 1)
        self.assertFalse(self.ctx.storage.get(self.ok).is_dead)
        self.assertTrue(self.ctx.storage.get(self.gone).is_dead)

    def test_wayback_fallback_records_snapshot(self):
        # enable wayback and stub the archive lookup (no real archive.org call)
        self.ctx.network.settings = Settings(
            network_enabled=True, allow_link_check=True, allow_wayback=True,
            allow_private_addresses=True)
        self.ctx.links.fetcher.wayback_url = (
            lambda url: "https://web.archive.org/web/2020/" + url)
        self.ctx.links.check_one(self.gone, use_wayback=True)
        self.assertIn("web.archive.org",
                      self.ctx.storage.get(self.gone).wayback_url)

    def test_check_blocked_when_link_check_off(self):
        cfg = Config(self.tmp / "off")
        ctx = ApplicationContext(cfg)  # defaults: everything off
        bid, _ = ctx.storage.upsert_bookmark(Bookmark(
            url="http://x", title="x", date_added=1, browser="F"))
        with self.assertRaises(NetworkDisabled):
            ctx.links.check_one(bid)
        ctx.close()


class WaybackParseTest(unittest.TestCase):
    def test_availability_json_parsed(self):
        import chronos.web.fetcher as fetchmod
        from chronos.net.policy import NetworkPolicy

        payload = json.dumps({"archived_snapshots": {"closest": {
            "available": True,
            "url": "http://web.archive.org/web/20200101/http://x.test/"}}}).encode()

        class FakeResp:
            def read(self_inner): return payload
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False

        orig = fetchmod.urlopen
        fetchmod.urlopen = lambda *a, **k: FakeResp()
        try:
            pol = NetworkPolicy(Settings(network_enabled=True, allow_wayback=True))
            f = fetchmod.PageFetcher(pol)
            snap = f.wayback_url("http://x.test/")
            self.assertIn("web.archive.org", snap)
        finally:
            fetchmod.urlopen = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
