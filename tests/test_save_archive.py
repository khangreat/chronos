"""v0.33 "Save & archive": Save Page Now against a stand-in archive.org server,
the switch that gates it, spacing and rate limits, the fixed Wayback lookup,
snapshots in citations, archive.today links, and WARC export (checked with the
independent warcio library when installed, and with a minimal reader always).
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402
from chronos.web import archive_org  # noqa: E402


class FakeIA:
    def __init__(self, mode="ok"):
        self.calls, self.mode, self.polls = [], mode, {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)

            def do_POST(self):
                body = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                outer.calls.append(("POST", self.path, dict(self.headers), body))
                if outer.mode == "busy":
                    self._send(429, {"message": "slow down"}); return
                url = body["url"][0]
                self._send(200, {"url": url, "job_id": f"spn2-{len(outer.calls)}"})

            def do_GET(self):
                outer.calls.append(("GET", self.path, dict(self.headers), None))
                job = self.path.rsplit("/", 1)[-1]
                n = outer.polls.get(job, 0); outer.polls[job] = n + 1
                if outer.mode == "error":
                    self._send(200, {"status": "error", "message": "Blocked by robots"}); return
                if n == 0:
                    self._send(200, {"status": "pending", "job_id": job}); return
                self._send(200, {"status": "success", "job_id": job,
                                 "timestamp": "20261031120000",
                                 "original_url": "https://example.org/page"})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


class SavePageNowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_ia_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "h")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/page", title="A page", date_added=1700000000,
            browser="F"))
        self.ia = FakeIA()

    def tearDown(self):
        self.ia.close(); self.ctx.close()

    def _on(self, **kw):
        st = replace(self.ctx.config.settings, network_enabled=True,
                     allow_archive_submit=True, **kw)
        self.ctx.config._settings = st; self.ctx.network.settings = st

    def test_off_sends_nothing(self):
        with self.assertRaises(NetworkDisabled):
            self.ctx.archive.save_to_internet_archive(self.bid, base=self.ia.base)
        st = replace(self.ctx.config.settings, network_enabled=True)   # master alone
        self.ctx.config._settings = st; self.ctx.network.settings = st
        with self.assertRaises(NetworkDisabled):
            self.ctx.archive.save_to_internet_archive(self.bid, base=self.ia.base)
        self.assertEqual(self.ia.calls, [])

    def test_save_polls_and_remembers_snapshot(self):
        self._on()
        slept = []
        snap = self.ctx.archive.save_to_internet_archive(
            self.bid, base=self.ia.base, sleep=slept.append, poll=1)
        self.assertEqual(snap, "https://web.archive.org/web/20261031120000/https://example.org/page")
        self.assertEqual(self.ctx.storage.get(self.bid).wayback_url, snap)
        post = self.ia.calls[0]
        self.assertEqual((post[0], post[1]), ("POST", "/save"))
        self.assertEqual(post[3]["url"], ["https://example.org/page"])
        self.assertEqual(post[2].get("Accept"), "application/json")
        self.assertNotIn("Authorization", post[2])
        self.assertEqual(slept, [1])                    # waited once while pending

    def test_keys_sent_and_spacing(self):
        self._on(ia_keys="acc:sec")
        self.assertEqual(archive_org.wait_between(self.ctx.config.settings), 9.0)
        b2, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/two", title="2", date_added=1, browser="F"))
        slept = []
        r = self.ctx.archive.save_many_to_internet_archive(
            [self.bid, b2], sleep=slept.append, base=self.ia.base, poll=1)
        self.assertEqual(len(r["saved"]), 2)
        self.assertIn(9.0, slept)                       # spaced between pages
        self.assertEqual(self.ia.calls[0][2].get("Authorization"), "LOW acc:sec")
        self._on(ia_keys="")
        self.assertEqual(archive_org.wait_between(self.ctx.config.settings), 21.0)

    def test_rate_limit_stops_the_batch(self):
        self._on()
        self.ia.close(); self.ia = FakeIA(mode="busy")
        b2, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/two", title="2", date_added=1, browser="F"))
        r = self.ctx.archive.save_many_to_internet_archive(
            [self.bid, b2], sleep=lambda s: None, base=self.ia.base)
        self.assertEqual(r["saved"], [])
        self.assertEqual(len(r["failed"]), 1)           # stopped, didn't hammer
        self.assertIn("too many", r["failed"][0][1])

    def test_archive_refusal_is_plain(self):
        self._on()
        self.ia.close(); self.ia = FakeIA(mode="error")
        with self.assertRaises(archive_org.ArchiveError) as e:
            self.ctx.archive.save_to_internet_archive(self.bid, base=self.ia.base,
                                                      sleep=lambda s: None)
        self.assertIn("robots", str(e.exception))

    def test_export_items_cannot_be_saved(self):
        self._on()
        b, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="fb-post://abc", title="mine", date_added=1, browser="F"))
        with self.assertRaises(ValueError):
            self.ctx.archive.save_to_internet_archive(b, base=self.ia.base)

    def test_snapshot_in_citation(self):
        self.ctx.storage.set_wayback(self.bid, "https://web.archive.org/web/2026/x")
        csl = self.ctx.provider().get_citation("https://example.org/page") \
            if hasattr(self.ctx.provider(), "get_citation") else None
        from chronos.interop import bookmark_to_csl
        item = bookmark_to_csl(self.ctx.storage.get(self.bid))
        self.assertEqual(item["archive_location"], "https://web.archive.org/web/2026/x")
        from bridgespec import validate_csl_item
        self.assertEqual(validate_csl_item(item), [])


class LookupAndLinksTest(unittest.TestCase):
    def test_wayback_lookup_encodes_the_address(self):
        from chronos.core.config import Settings
        from chronos.net.policy import NetworkPolicy
        from chronos.web.fetcher import PageFetcher
        seen = []

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self):
                return json.dumps({"archived_snapshots": {"closest": {
                    "available": True, "url": "http://web.archive.org/web/1/x"}}}).encode()

        def fake(url, timeout=0):
            seen.append(url); return R()
        f = PageFetcher(NetworkPolicy(Settings(network_enabled=True, allow_wayback=True)))
        with mock.patch("chronos.web.fetcher.urlopen", fake):
            snap = f.wayback_url("https://ex.org/a?b=1&c=2")
        self.assertIn("url=https%3A%2F%2Fex.org%2Fa%3Fb%3D1%26c%3D2", seen[0])
        self.assertTrue(snap.startswith("https://"))

    def test_archive_today_links(self):
        self.assertEqual(archive_org.archive_today_view("https://ex.org/a"),
                         "https://archive.ph/newest/https://ex.org/a")
        self.assertEqual(archive_org.archive_today_save("https://ex.org/a?x=1"),
                         "https://archive.ph/?run=1&url=https%3A%2F%2Fex.org%2Fa%3Fx%3D1")


class WarcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_warc_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "h")
        self.html = "<html><body><p>Brahui retroflex consonants — ڈ ڑ</p></body></html>"
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/brahui", title="Brahui", date_added=1700000000,
            browser="F"))
        self.ctx.archive.archive_from_html(self.bid, self.html, "https://example.org/brahui")
        self.ctx.snippets.capture(self.bid, "retroflex consonants")
        self.ctx.takeaways.add(self.bid, "kept with the page")
        self.nocopy, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/none", title="no copy", date_added=1, browser="F"))
        self.out = self.tmp / "t.warc.gz"

    def tearDown(self):
        self.ctx.close()

    def test_minimal_reader(self):
        from chronos.export.warc import write_warc
        self.assertEqual(write_warc(self.ctx, self.out), 1)     # only pages with a copy
        raw = gzip.decompress(self.out.read_bytes()).decode("utf-8")
        types = [l.split(": ")[1] for l in raw.splitlines() if l.startswith("WARC-Type:")]
        self.assertEqual(types, ["warcinfo", "resource", "metadata"])
        self.assertIn("ڈ ڑ", raw)
        self.assertIn('"takeaways": ["kept with the page"]', raw)

    def test_warcio_reads_it(self):
        try:
            from warcio.archiveiterator import ArchiveIterator
        except ImportError:
            self.skipTest("warcio not installed")
        from chronos.export.warc import write_warc
        write_warc(self.ctx, self.out)
        recs = []
        with open(self.out, "rb") as f:
            for r in ArchiveIterator(f, check_digests="raise"):   # digests verified
                recs.append((r.rec_type, r.rec_headers.get_header("WARC-Target-URI"),
                             r.content_stream().read()))
        self.assertEqual([t for t, _, _ in recs], ["warcinfo", "resource", "metadata"])
        self.assertEqual(recs[1][1], "https://example.org/brahui")
        self.assertEqual(recs[1][2].decode("utf-8"), self.html)
        self.assertEqual(json.loads(recs[2][2])["quotes"], ["retroflex consonants"])


class CliHelpTest(unittest.TestCase):
    def test_help_lists_every_command(self):
        import contextlib, io
        from chronos import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["--help"])
        for name in cli.COMMANDS:
            self.assertIn(name, buf.getvalue())
        self.assertIn("1 item in your archive", json.loads(Path(
            cli.__file__).parent.joinpath("gui/locale/en.json").read_text("utf-8"))
            ["status.summary_one"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
