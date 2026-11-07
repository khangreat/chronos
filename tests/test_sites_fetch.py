"""v0.37 "Site by site": fetching everything politely (one request at a time
per site, paced), honest outcomes (gone vs refused vs busy), PDFs and text kept
properly, redirects recorded, your own network protected, rules per site that
really decide, resumable runs, and the Fetch and Sites windows.

A stand-in website runs on this computer, so these tests turn on "fetch
addresses on my own network" — except the ones proving that, when it's off,
nothing on your network is ever touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.web import fetcher as fetcher_mod  # noqa: E402
from chronos.web.fetch_queue import FetchEngine  # noqa: E402
from chronos.web.sites import SiteRules, domain_of, is_private_url, site_stats  # noqa: E402

ARTICLE = ("<html><head><title>Brahui verbs</title><meta name='author' content='Ada'>"
           "</head><body><nav>Home Login Shop</nav><article><h1>Brahui verbs</h1>"
           "<p>Brahui is a Dravidian language spoken in Balochistan.</p></article>"
           "</body></html>")
NO_ARTICLE = ("<html><body><div>Home About Login Shop Subscribe Newsletter</div><div><p>"
              + "Brahui is a Dravidian language spoken in Balochistan and Afghanistan. " * 5
              + "</p><p>" + "Its verbs agree with the subject in person and number. " * 5
              + "</p></div><div>Copyright privacy terms cookies</div></body></html>")


def make_pdf(text: str, title: str) -> bytes:
    """A small, valid one-page PDF with real text (for the PDF path)."""
    content = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 144] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Title (" + title.encode() + b") >>"]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    return bytes(out)


class Site:
    """A stand-in website with every kind of answer a real one gives."""

    def __init__(self):
        self.hits, self.inflight, self.max_inflight = [], 0, 0
        self.busy_once = True
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _route(self):
                with outer.lock:
                    outer.hits.append((self.command, self.path, time.monotonic()))
                    outer.inflight += 1
                    outer.max_inflight = max(outer.max_inflight, outer.inflight)
                try:
                    time.sleep(0.05)
                    p = self.path
                    if p.startswith("/page"):
                        self._send(200, ARTICLE.encode())
                    elif p == "/plain-article":
                        self._send(200, NO_ARTICLE.encode())
                    elif p == "/doc.pdf":
                        self._send(200, make_pdf("Brahui grammar notes", "Grammar"),
                                   "application/pdf")
                    elif p == "/notes.txt":
                        self._send(200, "Plain notes about Kurukh.".encode(), "text/plain")
                    elif p == "/gone":
                        self._send(404, b"no")
                    elif p == "/refused":
                        self._send(403, b"no")
                    elif p == "/picture.png":
                        self._send(200, b"\x89PNG....", "image/png")
                    elif p == "/old":
                        self._send(301, b"", extra={"Location": "/page-new"})
                    elif p == "/busy":
                        if outer.busy_once:
                            outer.busy_once = False
                            self._send(429, b"slow down")
                        else:
                            self._send(200, ARTICLE.encode())
                    elif p == "/nohead":
                        if self.command == "HEAD":
                            self._send(405, b"")
                        else:
                            self._send(200, ARTICLE.encode())
                    else:
                        self._send(404, b"")
                finally:
                    with outer.lock:
                        outer.inflight -= 1

            do_GET = do_HEAD = _route

        # all IPv4 loopback addresses, so 127.0.0.1 and 127.0.0.2 are two "sites"
        # (on Windows "localhost" tries IPv6 first, which would skew timing)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path, host="127.0.0.1"):
        return f"http://{host}:{self.port}{path}"

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


def _ctx(**kw):
    tmp = Path(tempfile.mkdtemp(prefix="chronos_fetch_")).resolve()
    ctx = ApplicationContext.for_dir(tmp / "h")
    opts = dict(network_enabled=True, allow_page_fetch=True, allow_link_check=True,
                allow_private_addresses=True)
    opts.update(kw)
    st = replace(ctx.config.settings, **opts)
    ctx.config.save_settings(st)            # background runs read them from disk
    ctx.config._settings = st
    ctx.network.settings = st
    return tmp, ctx


def _add(ctx, url, title="t", browser="F"):
    bid, _ = ctx.storage.upsert_bookmark(Bookmark(url=url, title=title, date_added=1700000000,
                                                  browser=browser))
    ctx.storage.conn.commit()
    return bid


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.tmp, self.ctx = _ctx()
        # the stand-in site answers fast; keep the pace short so tests are quick
        SiteRules(self.ctx.storage, True).set("127.0.0.1", "fetch", pace=0.15)
        SiteRules(self.ctx.storage, True).set("127.0.0.2", "fetch", pace=0.15)

    def tearDown(self):
        self.site.close(); self.ctx.close()

    def test_every_answer_is_handled_honestly(self):
        u = self.site.url
        ids = {k: _add(self.ctx, u(p)) for k, p in [
            ("page", "/page"), ("pdf", "/doc.pdf"), ("txt", "/notes.txt"),
            ("gone", "/gone"), ("refused", "/refused"), ("png", "/picture.png"),
            ("old", "/old"), ("busy", "/busy")]}
        eng = FetchEngine(self.ctx, sleep=time.sleep)
        res = eng.run(eng.plan())
        st, ar = self.ctx.storage, self.ctx.archive
        # page: kept with its text
        self.assertEqual(st.get_archive(ids["page"])["mime"], "text/html")
        self.assertIn("Dravidian", st.get(ids["page"]).page_text)
        # PDF: kept as a PDF (not decoded as text), its words searchable
        self.assertEqual(st.get_archive(ids["pdf"])["mime"], "application/pdf")
        self.assertTrue(ar.read_bytes(ids["pdf"]).startswith(b"%PDF"))
        self.assertIsNone(ar.read_html(ids["pdf"]))
        self.assertIn("Brahui grammar notes", st.get(ids["pdf"]).page_text)
        self.assertEqual(st.get_archive(ids["txt"])["mime"], "text/plain")
        # gone vs refused: only "gone" counts as dead
        self.assertTrue(st.get(ids["gone"]).is_dead)
        self.assertFalse(st.get(ids["refused"]).is_dead)
        self.assertEqual(st.fetch_status(ids["refused"])["status"], "blocked")
        self.assertIn("refused", st.fetch_status(ids["refused"])["reason"])
        self.assertEqual(st.fetch_status(ids["png"])["status"], "not_page")
        self.assertFalse(ar.has_archive(ids["png"]))
        # redirect recorded
        moved = st.fetch_status(ids["old"])
        self.assertEqual(moved["status"], "moved")
        self.assertTrue(moved["final_url"].endswith("/page-new"))
        # busy once, then saved on the retry
        self.assertTrue(ar.has_archive(ids["busy"]))
        self.assertEqual(res.counts["dead"], 1)
        self.assertIn("refused by the site", res.summary())

    def test_one_request_at_a_time_per_site_paced(self):
        for i in range(4):
            _add(self.ctx, self.site.url(f"/page{i}"))
        eng = FetchEngine(self.ctx, workers=4)
        eng.run(eng.plan())
        self.assertEqual(self.site.max_inflight, 1)            # one site: never parallel
        times = sorted(t for _, _, t in self.site.hits)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g >= 0.12 for g in gaps), gaps)    # pace respected

    def test_two_sites_go_side_by_side(self):
        for i in range(3):
            _add(self.ctx, self.site.url(f"/page{i}"))
            _add(self.ctx, self.site.url(f"/page{i}", host="127.0.0.2"))
        eng = FetchEngine(self.ctx, workers=4)
        eng.run(eng.plan())
        self.assertEqual(self.site.max_inflight, 2)

    def test_stop_and_continue(self):
        for i in range(6):
            _add(self.ctx, self.site.url(f"/page{i}"))
        eng = FetchEngine(self.ctx)
        done = []
        res = eng.run(eng.plan(), progress=lambda d, t, j, o: done.append(d),
                      should_stop=lambda: len(done) >= 2)
        self.assertTrue(res.stopped)
        left = eng.plan()
        self.assertLess(len(left.jobs), 6)
        self.assertGreater(left.skipped["saved"]["127.0.0.1"], 0)
        res2 = eng.run(left)
        self.assertEqual(self.ctx.storage.archive_count(), 6)
        self.assertFalse(res2.stopped)

    def test_plan_explains_what_it_skips(self):
        _add(self.ctx, "https://x.com/someone/status/1")
        _add(self.ctx, "https://www.facebook.com/post/2")
        _add(self.ctx, "reddit-post://abc", browser="Reddit")
        _add(self.ctx, "https://www.google.com/search?q=brahui")
        refused = _add(self.ctx, self.site.url("/refused"))
        FetchEngine(self.ctx).run(FetchEngine(self.ctx).plan([refused]))
        plan = FetchEngine(self.ctx).plan()
        self.assertEqual(sum(plan.skipped["login"].values()), 2)
        self.assertEqual(sum(plan.skipped["not_web"].values()), 1)
        self.assertEqual(sum(plan.skipped["skip"].values()), 1)       # a search
        self.assertEqual(sum(plan.skipped["recent"].values()), 1)     # refused lately
        text = plan.summary()
        self.assertIn("needs login", text)
        self.assertIn("x.com", text)
        self.assertEqual(len(FetchEngine(self.ctx).plan(again=True).jobs), 1)

    def test_link_check_tells_gone_from_refused(self):
        a = _add(self.ctx, self.site.url("/nohead"))      # refuses HEAD, fine with GET
        g = _add(self.ctx, self.site.url("/gone"))
        r = _add(self.ctx, self.site.url("/refused"))
        eng = FetchEngine(self.ctx)
        res = eng.run(eng.plan(mode="check"))
        st = self.ctx.storage
        self.assertFalse(st.get(a).is_dead)
        self.assertTrue(st.get(g).is_dead)
        self.assertFalse(st.get(r).is_dead)
        self.assertEqual(res.counts["blocked"], 1)
        self.assertFalse(self.ctx.archive.has_archive(a))   # checking keeps nothing

    def test_site_extractor_rule_is_used(self):
        from chronos.web.extract import available_extractors
        if "trafilatura" not in available_extractors():
            self.skipTest("Trafilatura not installed")
        a = _add(self.ctx, self.site.url("/plain-article"))
        b = _add(self.ctx, self.site.url("/plain-article", host="127.0.0.2"))
        SiteRules(self.ctx.storage, True).set("127.0.0.2", "fetch", pace=0.15,
                                              extractor="builtin")
        eng = FetchEngine(self.ctx)
        eng.run(eng.plan())
        self.assertNotIn("Subscribe", self.ctx.storage.get(a).page_text)   # auto
        self.assertIn("Subscribe", self.ctx.storage.get(b).page_text)      # site rule

    def test_reader_save_is_one_item_through_the_rules(self):
        bid = _add(self.ctx, self.site.url("/page"))
        r = self.ctx.archive.archive(bid)
        self.assertGreater(r.bytes, 0)
        x = _add(self.ctx, "https://x.com/a/status/1")
        with self.assertRaises(RuntimeError) as e:
            self.ctx.archive.archive(x)
        self.assertIn("browser extension", str(e.exception))
        self.assertEqual(len([h for h in self.site.hits if "x.com" in h[1]]), 0)


class SafetyTest(unittest.TestCase):
    def test_private_addresses(self):
        for u in ("http://localhost/a", "http://127.0.0.1:8080/", "http://192.168.1.1/admin",
                  "http://10.0.0.5/", "http://172.16.3.4/", "http://[::1]/", "http://router/",
                  "http://nas.local/wiki", "http://169.254.1.1/", "file:///etc/passwd",
                  "ftp://example.org/"):
            self.assertTrue(is_private_url(u), u)
        for u in ("https://example.org/", "http://8.8.8.8/", "https://sub.wikipedia.org/x"):
            self.assertFalse(is_private_url(u), u)

    def test_own_network_never_touched_when_off(self):
        site = Site()
        tmp, ctx = _ctx(allow_private_addresses=False)
        try:
            bid = _add(ctx, site.url("/page"))
            plan = FetchEngine(ctx).plan()
            self.assertEqual(plan.jobs, [])
            self.assertEqual(sum(plan.skipped["private"].values()), 1)
            out = fetcher_mod.PageFetcher(ctx.network).fetch_document(site.url("/page"))
            self.assertEqual(out.status, "private")
            self.assertEqual(site.hits, [])                     # not one request
            self.assertIn("own network", ctx.archive.__class__.__name__ + str(
                FetchEngine(ctx).fetch_one(bid).reason))
        finally:
            site.close(); ctx.close()

    def test_web_cannot_redirect_into_your_network(self):
        from urllib.request import Request
        h = fetcher_mod._SafeRedirect(allow_private=False)
        req = Request("https://example.org/a")
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {},
                                                "https://example.org/b"))   # normal: fine
        with self.assertRaises(fetcher_mod.HTTPError):
            h.redirect_request(req, None, 302, "Found", {}, "http://192.168.0.1/admin")
        allowed = fetcher_mod._SafeRedirect(allow_private=True)
        self.assertIsNotNone(allowed.redirect_request(req, None, 302, "Found", {},
                                                      "http://192.168.0.1/x"))

    def test_shared_copy_survives_removing_one_item(self):
        tmp, ctx = _ctx()
        try:
            a = _add(ctx, "https://example.org/a")
            b = _add(ctx, "https://example.org/b")
            ctx.archive.archive_from_html(a, ARTICLE, "https://example.org/a")
            ctx.archive.archive_from_html(b, ARTICLE, "https://example.org/b")
            path = ctx.storage.get_archive(a)["path"]
            self.assertEqual(path, ctx.storage.get_archive(b)["path"])   # same content
            ctx.removal.remove_many([a])
            self.assertTrue(Path(path).exists())
            self.assertIn("Dravidian", ctx.archive.read_html(b))
        finally:
            ctx.close()


class SitesTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx(allow_private_addresses=False)

    def tearDown(self):
        self.ctx.close()

    def test_domain_stored_and_rules(self):
        _add(self.ctx, "https://www.Example.org/a")
        self.assertEqual(domain_of("https://www.Example.org:8080/a"), "example.org")
        row = self.ctx.storage.conn.execute("SELECT domain FROM bookmarks").fetchone()
        self.assertEqual(row[0], "example.org")
        r = SiteRules(self.ctx.storage)
        self.assertEqual(r.for_url("https://mobile.x.com/a").mode, "login")       # subdomain
        self.assertEqual(r.for_url("https://en.wikipedia.org/wiki/Brahui").pace, 1.0)
        self.assertEqual(r.for_url("https://www.youtube.com/watch?v=x").mode, "metadata")
        r.set("x.com", "skip")                                                  # yours wins
        self.assertEqual(SiteRules(self.ctx.storage).for_url("https://x.com/a").mode, "skip")
        r.clear("x.com")
        self.assertEqual(SiteRules(self.ctx.storage).for_url("https://x.com/a").mode, "login")
        with self.assertRaises(ValueError):
            r.set("example.org", "private")

    def test_site_numbers(self):
        a = _add(self.ctx, "https://example.org/a")
        _add(self.ctx, "https://example.org/b")
        _add(self.ctx, "https://other.net/c")
        self.ctx.archive.archive_from_html(a, ARTICLE, "https://example.org/a")
        self.ctx.storage.log_fetch(a, "blocked", "copy", 403, "refused")
        s = {x.domain: x for x in site_stats(self.ctx)}
        self.assertEqual((s["example.org"].items, s["example.org"].offline,
                          s["example.org"].problems), (2, 1, 1))
        self.assertAlmostEqual(s["example.org"].coverage, 0.5)

    def test_metadata_answer_fills_title_and_channel(self):
        bid = self.ctx.videos.ensure(__import__("chronos.web.video", fromlist=["x"])
                                     .parse_video("https://youtu.be/dQw4w9WgXcQ"))
        eng = FetchEngine(self.ctx)
        job = eng.plan([bid]).jobs[0]
        self.assertEqual(job.kind, "metadata")
        out = fetcher_mod.FetchOutcome(job.url, "ok", 200, kind="json",
                                       body=b'{"title": "A Brahui talk", "author_name": '
                                            b'"Quetta Channel", "provider_name": "YouTube"}')
        eng._keep(job, out)
        b = self.ctx.storage.get(bid)
        self.assertEqual((b.title, b.byline), ("A Brahui talk", "Quetta Channel"))

    def test_migration_adds_domains_to_old_items(self):
        import sqlite3
        from chronos.core import migrations
        db = self.tmp / "old.db"
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        migrations.get_db_version(con)                 # creates the version table
        for v, fn in sorted(migrations.MIGRATIONS, key=lambda m: m[0]):
            if v > 10:
                break
            fn(con)
            migrations.set_db_version(con, v)
        con.execute("INSERT INTO bookmarks (browser,title,url,date_added,year,month) "
                    "VALUES ('F','t','https://www.kept.org/x',1,2023,1)")
        con.commit(); con.close()
        from chronos.core.storage import Storage
        s = Storage(db)
        self.assertEqual(s.version, max(v for v, _ in migrations.MIGRATIONS))
        self.assertEqual(s.conn.execute("SELECT domain, title FROM bookmarks").fetchone()[:],
                         ("kept.org", "t"))
        s.close()


try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class WindowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fetch_window_plans_runs_and_explains_network(self):
        from chronos.gui.fetch_dialog import FetchDialog
        site = Site()
        tmp, ctx = _ctx()
        try:
            SiteRules(ctx.storage, True).set("127.0.0.1", "fetch", pace=0.1)
            for i in range(3):
                _add(ctx, site.url(f"/page{i}"))
            _add(ctx, "https://x.com/a/status/1")
            d = FetchDialog(ctx)
            self.assertIn("3 items to fetch from 1 site", d.plan_label.text())
            self.assertIn("needs login", d.plan_label.text())
            self.assertTrue(d.start_btn.isEnabled())
            d.start()
            t = time.time()
            while d.run_thread is not None and time.time() - t < 30:
                self.app.processEvents(); time.sleep(0.02)
            self.assertIn("3 saved", d.result.toPlainText())
            self.assertEqual(ctx.storage.archive_count(), 3)
            ctx.network.settings = replace(ctx.network.settings, network_enabled=False)
            d.refresh_plan()
            self.assertFalse(d.start_btn.isEnabled())
            self.assertTrue(d.net_note.isVisibleTo(d))
        finally:
            site.close(); ctx.close()

    def test_sites_window_rules_and_show(self):
        from chronos.gui.sites_dialog import SitesDialog
        tmp, ctx = _ctx(allow_private_addresses=False)
        try:
            for i in range(3):
                _add(ctx, f"https://example.org/{i}")
            _add(ctx, "https://x.com/a/status/1")
            d = SitesDialog(ctx)
            self.assertEqual(d.table.item(0, 0).text(), "example.org")
            self.assertIn("2 sites, 4 items", d.summary.text())
            d.select_domain("x.com")
            self.assertIn("logged-in", d.rule_note.text())
            self.assertFalse(d.fetch_btn.isEnabled())
            d.select_domain("example.org")
            d.mode.setCurrentIndex(d.mode.findData("skip")); d._save_rule()
            self.assertEqual(SiteRules(ctx.storage).for_domain("example.org").mode, "skip")
            shown = []
            d.show_site.connect(shown.append)
            d.select_domain("example.org"); d._show()
            self.assertEqual(shown, ["example.org"])
            self.assertEqual(len(d.chart.rows), 2)
        finally:
            ctx.close()

    def test_sites_window_right_to_left(self):
        from PySide6.QtCore import Qt
        from chronos.gui.sites_dialog import SitesDialog
        tmp, ctx = _ctx(allow_private_addresses=False)
        self.app.setLayoutDirection(Qt.RightToLeft)          # Arabic / Urdu interface
        try:
            _add(ctx, "https://example.org/a"); _add(ctx, "https://x.com/a/status/1")
            d = SitesDialog(ctx)
            d.select_domain("x.com")
            self.assertEqual(d.current_domain(), "x.com")
            self.assertIn("logged-in", d.rule_note.text())
        finally:
            self.app.setLayoutDirection(Qt.LeftToRight)
            ctx.close()

    def test_library_has_sites_and_reader_explains(self):
        from chronos.gui.main_window import MainWindow
        tmp, ctx = _ctx(allow_private_addresses=False)
        try:
            bid = _add(ctx, "https://example.org/a")
            x = _add(ctx, "https://x.com/a/status/1")
            ctx.storage.log_fetch(bid, "blocked", "copy", 403, "The site refused.")
            w = MainWindow(ctx)
            lib = w.timeline.library
            heads = [lib.topLevelItem(i).text(0) for i in range(lib.topLevelItemCount())]
            self.assertIn("Sites", heads)
            w._show_bookmark(bid)
            self.assertIn("refused by the site", w.reader.fetch_note.text())
            w._show_bookmark(x)
            self.assertIn("browser extension", w.reader.fetch_note.text())
            w._show_library("site", "example.org")
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
