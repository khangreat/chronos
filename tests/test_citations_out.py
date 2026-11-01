"""v0.34 "Citations out": Zotero (against a stand-in Zotero connector on this
computer), Nawishtar's Reading folder (read back with a copy of Nawishtar's own
a127 page reader), a Khwānōk reading book (checked with the W3C's EPUBCheck
when Java is available, and structurally always), and fixed BibTeX/RIS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.cite import zotero  # noqa: E402

PAGE = """<html><head><meta name="author" content="Ada Lindqvist">
<meta property="og:site_name" content="Field Notes">
<meta property="article:published_time" content="2026-06-30T10:00:00Z"></head>
<body><nav>Home · About</nav><article><h1>Brahui verbs</h1>
<p>Brahui is a Dravidian language spoken in Balochistan.</p>
<p>براہوئی زبان میں ڈ اور ڑ retroflex consonants ہیں۔</p>
<p>Verbs agree with the subject in person and number.</p>
</article><footer>© Field Notes</footer></body></html>"""
WB = "https://web.archive.org/web/20261031120000/https://example.org/brahui"


def _ctx():
    tmp = Path(tempfile.mkdtemp(prefix="chronos_cite_"))
    ctx = ApplicationContext.for_dir(tmp / "h")
    b, _ = ctx.storage.upsert_bookmark(Bookmark(
        url="https://example.org/brahui", title="Brahui verbs", date_added=1700000000,
        browser="Firefox"))
    ctx.archive.archive_from_html(b, PAGE, "https://example.org/brahui")
    ctx.snippets.capture(b, "a Dravidian language")
    ctx.takeaways.add(b, "compare with Kurukh verbs")
    ctx.storage.set_tags(b, ["brahui", "linguistics"])
    ctx.storage.set_wayback(b, WB)
    p, _ = ctx.storage.upsert_bookmark(Bookmark(
        url="reddit-post://abc", title="Learning Brahui", date_added=1700000100,
        browser="Reddit", kind="social_post", site_name="Reddit", byline="u/hdf",
        page_text="Any good books for learning Brahui?\nI found one grammar so far."))
    v, _ = ctx.storage.upsert_bookmark(Bookmark(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Brahui talk",
        date_added=1700000200, browser="F", site_name="YouTube"))
    e, _ = ctx.storage.upsert_bookmark(Bookmark(
        url="https://example.org/empty", title="Not read yet", date_added=1700000300,
        browser="F"))
    return tmp, ctx, b, p, v, e


# --------------------------------------------------------------------------- #
# Zotero
# --------------------------------------------------------------------------- #
class FakeZotero:
    def __init__(self, mode="ok"):
        self.mode, self.posts, self.pings = mode, [], 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b""):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def do_GET(self):
                if self.path == "/connector/ping":
                    outer.pings += 1
                    self._send(200, b"Zotero is running")
                else:
                    self._send(404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.posts.append((self.path, dict(self.headers), body))
                if outer.mode == "old":
                    self._send(404); return
                if outer.mode == "clash" and len(outer.posts) == 1:
                    self._send(409, b"SESSION_EXISTS"); return
                self._send(201)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


class ZoteroTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx, self.b, self.p, self.v, self.e = _ctx()
        self.z = FakeZotero()

    def tearDown(self):
        self.z.close(); self.ctx.close()

    def _items(self):
        return {i["id"]: i for _, _, body in self.z.posts for i in body["items"]}

    def test_sends_with_notes_types_and_archive_while_offline(self):
        self.assertFalse(self.ctx.config.settings.network_enabled)   # stays on this computer
        n = zotero.send_to_zotero(self.ctx, [self.b, self.p, self.v], base=self.z.base)
        self.assertEqual(n, 3)
        path, headers, body = self.z.posts[0]
        self.assertEqual(path, "/connector/saveItems")
        self.assertEqual({k.lower(): v for k, v in headers.items()}
                         ["x-zotero-connector-api-version"], "3")
        self.assertIn("sessionID", body)
        it = self._items()
        page = it[f"chronos-{self.b}"]
        self.assertEqual(page["itemType"], "webpage")
        self.assertEqual(page["websiteTitle"], "Field Notes")
        self.assertEqual(page["creators"], [{"firstName": "Ada", "lastName": "Lindqvist",
                                             "creatorType": "author"}])
        self.assertEqual(page["date"], "2026-06-30")
        self.assertRegex(page["accessDate"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual(sorted(t["tag"] for t in page["tags"]), ["brahui", "linguistics"])
        note = page["notes"][0]["note"]
        self.assertIn("a Dravidian language", note)
        self.assertIn("compare with Kurukh verbs", note)
        self.assertIn(f"archive_location: {WB}", page["extra"])
        self.assertEqual(page["attachments"][0]["url"], WB)
        self.assertFalse(page["attachments"][0]["snapshot"])
        post = it[f"chronos-{self.p}"]
        self.assertEqual((post["itemType"], post["forumTitle"], post["postType"]),
                         ("forumPost", "Reddit", "Post"))
        self.assertNotIn("url", post)                     # reddit-post:// isn't a web address
        self.assertEqual(post["creators"][0], {"lastName": "u/hdf", "creatorType": "author",
                                               "fieldMode": 1})
        vid = it[f"chronos-{self.v}"]
        self.assertEqual((vid["itemType"], vid["libraryCatalog"]),
                         ("videoRecording", "YouTube"))

    def test_html_in_notes_is_escaped(self):
        self.ctx.takeaways.add(self.b, "<script>x</script> & more")
        zotero.send_to_zotero(self.ctx, [self.b], base=self.z.base)
        note = self._items()[f"chronos-{self.b}"]["notes"][0]["note"]
        self.assertNotIn("<script>", note)
        self.assertIn("&lt;script&gt;x&lt;/script&gt; &amp; more", note)

    def test_only_this_computer(self):
        calls = []
        with mock.patch.object(zotero, "_open", lambda *a, **k: calls.append(a)):
            for base in ("http://example.org:23119", "http://192.168.1.5:23119",
                         "http://127.0.0.1.evil.example:23119"):
                with self.assertRaises(ValueError):
                    zotero.send_to_zotero(self.ctx, [self.b], base=base)
        self.assertEqual(calls, [])                       # refused before any request

    def test_system_proxy_is_bypassed(self):
        env = {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
               "no_proxy": "", "NO_PROXY": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(zotero.send_to_zotero(self.ctx, [self.b], base=self.z.base), 1)

    def test_not_running_is_plain(self):
        self.z.close()
        with self.assertRaises(zotero.ZoteroError) as e:
            zotero.send_to_zotero(self.ctx, [self.b], base=self.z.base)
        self.assertIn("isn't running", str(e.exception))
        self.z = FakeZotero()                             # for tearDown

    def test_session_clash_retries_once(self):
        self.z.close(); self.z = FakeZotero("clash")
        self.assertEqual(zotero.send_to_zotero(self.ctx, [self.b], base=self.z.base), 1)
        self.assertEqual(len(self.z.posts), 2)
        self.assertNotEqual(self.z.posts[0][2]["sessionID"], self.z.posts[1][2]["sessionID"])

    def test_old_zotero_is_explained(self):
        self.z.close(); self.z = FakeZotero("old")
        with self.assertRaises(zotero.ZoteroError) as e:
            zotero.send_to_zotero(self.ctx, [self.b], base=self.z.base)
        self.assertIn("Zotero 7", str(e.exception))

    def test_batches(self):
        ids = []
        for i in range(120):
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://ex.org/{i}", title=str(i), date_added=1, browser="F"))
            ids.append(bid)
        self.assertEqual(zotero.send_to_zotero(self.ctx, ids, base=self.z.base), 120)
        self.assertEqual([len(b["items"]) for _, _, b in self.z.posts], [50, 50, 20])


# --------------------------------------------------------------------------- #
# Nawishtar Reading folder — read back the way Nawishtar a127 reads a page
# --------------------------------------------------------------------------- #
class _NawishtarText(HTMLParser):
    """Copy of Nawishtar a127's page reader (packs/references/reading.py)."""
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "div",
             "td", "dd", "dt", "figcaption", "section", "article", "br", "tr"}
    SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer",
            "form", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras, self.buf, self.skip = [], [], 0
        self.meta, self.title, self._in_title = {}, "", False

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        if t:
            self.paras.append(t)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"])
        if tag == "link" and (a.get("rel") or "").lower() == "canonical" and a.get("href"):
            self.meta.setdefault("canonical", a["href"])
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self.skip:
            self.buf.append(data)


def nawishtar_read(path: Path) -> dict:
    p = _NawishtarText()
    p.feed(path.read_text(encoding="utf-8")); p.close(); p._flush()
    m = p.meta
    title = re.sub(r"\s+", " ", (m.get("og:title") or p.title or path.stem).strip())
    return {"title": title, "url": m.get("og:url") or m.get("canonical") or "",
            "author": m.get("author"), "site": m.get("og:site_name"),
            "published": m.get("article:published_time"),
            "archived": m.get("chronos:archived") or m.get("archived"),
            "paras": [x for x in p.paras if x != title]}


class ReadingFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx, self.b, self.p, self.v, self.e = _ctx()
        self.out = self.tmp / "Nawishtar Reading" / "Chronos"

    def tearDown(self):
        self.ctx.close()

    def _write(self, ids=None):
        from chronos.cite.reading import write_reading_folder
        return write_reading_folder(self.ctx, self.out, ids)

    def test_nawishtar_reads_what_chronos_writes(self):
        r = self._write([self.b, self.p, self.e])
        self.assertEqual(r["written"], 2)
        self.assertEqual([i for i, _ in r["skipped"]], [self.e])     # nothing to read
        page = next(self.out.glob(f"*chronos-{self.b}].html"))
        got = nawishtar_read(page)
        self.assertEqual(got["url"], "https://example.org/brahui")
        self.assertEqual(got["author"], "Ada Lindqvist")
        self.assertEqual(got["site"], "Field Notes")
        self.assertTrue(got["published"].startswith("2026-06-30"))
        arch = self.ctx.storage.get_archive(self.b)
        at = arch["archived_at"] if isinstance(arch, dict) else arch.archived_at
        self.assertEqual(got["archived"],
                         datetime.fromtimestamp(at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        # exactly the article's paragraphs: no nav/footer, no Chronos furniture
        self.assertEqual(got["paras"], [
            "Brahui is a Dravidian language spoken in Balochistan.",
            "براہوئی زبان میں ڈ اور ڑ retroflex consonants ہیں۔",
            "Verbs agree with the subject in person and number."])
        side = json.loads(page.with_name(page.stem + ".chronos.json").read_text("utf-8"))
        self.assertEqual(side["quotes"], ["a Dravidian language"])        # yours, set apart
        self.assertEqual(side["takeaways"], ["compare with Kurukh verbs"])
        self.assertEqual(side["csl"]["archive_location"], WB)
        self.assertNotIn("Kurukh", page.read_text("utf-8"))               # never in the body

    def test_export_post_has_no_web_address(self):
        self._write([self.p])
        got = nawishtar_read(next(self.out.glob(f"*chronos-{self.p}].html")))
        self.assertEqual(got["url"], "")
        self.assertEqual(got["paras"], ["Any good books for learning Brahui?",
                                        "I found one grammar so far."])

    def test_writing_again_replaces_not_duplicates(self):
        self._write([self.b])
        self.ctx.storage.conn.execute("UPDATE bookmarks SET title=?, page_title=? WHERE id=?",
                                      ("Brahui verbs, revised", "Brahui verbs, revised", self.b))
        self.ctx.storage.conn.commit()
        self._write([self.b]); self._write([self.b])
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(len(names), 2, names)                             # one .html + one .json
        self.assertTrue(names[0].startswith("Brahui verbs, revised"))

    def test_unsafe_titles_make_safe_names(self):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://ex.org/x", title='a/b\\c:d*e?"f<g>|h', date_added=1, browser="F",
            page_text="Some text that is long enough."))
        self._write([bid])
        name = next(self.out.glob(f"*chronos-{bid}].html")).name
        self.assertFalse(set('/\\:*?"<>|') & set(name.replace(f"[chronos-{bid}].html", "")))


# --------------------------------------------------------------------------- #
# Khwānōk reading book (EPUB 3)
# --------------------------------------------------------------------------- #
def _epubcheck_jar():
    if not shutil.which("java"):
        return None
    try:
        import epubcheck
        jar = Path(epubcheck.__file__).with_name("epubcheck.jar")
        return jar if jar.exists() else None
    except ImportError:
        return None


class EpubTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx, self.b, self.p, self.v, self.e = _ctx()
        self.out = self.tmp / "book.epub"

    def tearDown(self):
        self.ctx.close()

    def _write(self, ids):
        from chronos.cite.epub import write_epub
        return write_epub(self.ctx, self.out, ids, title="Brahui reading")

    def test_structure(self):
        self.ctx.takeaways.add(self.b, "odd\x0bcontrol char & <angle>")    # must stay valid XML
        r = self._write([self.b, self.p, self.e])
        self.assertEqual((r["chapters"], [i for i, _ in r["skipped"]]), (2, [self.e]))
        with zipfile.ZipFile(self.out) as z:
            first = z.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            self.assertEqual(z.read("mimetype"), b"application/epub+zip")
            for n in z.namelist():
                if n.endswith((".xhtml", ".opf", ".xml")):
                    ET.fromstring(z.read(n))                         # well-formed
            c1 = z.read("OEBPS/c1.xhtml").decode("utf-8")
        self.assertIn("ڈ اور ڑ", c1)
        self.assertIn('dir="auto"', c1)
        self.assertIn("Your notes in Chronos", c1)
        self.assertIn("&lt;angle&gt;", c1)
        self.assertIn(WB, c1)

    def test_nothing_to_read(self):
        with self.assertRaises(ValueError):
            self._write([self.e])
        self.assertFalse(self.out.exists())

    def test_ebooklib_reads_it(self):
        try:
            import ebooklib
            from ebooklib import epub
        except ImportError:
            self.skipTest("ebooklib not installed")
        self._write([self.b, self.p])
        book = epub.read_epub(str(self.out), {"ignore_ncx": True})
        self.assertEqual(book.get_metadata("DC", "title")[0][0], "Brahui reading")
        docs = [d for d in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
                if d.get_name().startswith("c")]
        self.assertEqual(len(docs), 2)

    @unittest.skipUnless(_epubcheck_jar(), "Java + EPUBCheck not available")
    def test_epubcheck_passes(self):
        self.ctx.takeaways.add(self.b, "odd\x0bcontrol char & <angle>")
        self._write([self.b, self.p, self.v] if self.ctx.storage.get(self.v).page_text
                    else [self.b, self.p])
        r = subprocess.run(["java", "-jar", str(_epubcheck_jar()), str(self.out)],
                           capture_output=True, text=True, timeout=180)
        self.assertIn("0 fatals / 0 errors / 0 warnings", r.stdout + r.stderr,
                      r.stdout + r.stderr)


# --------------------------------------------------------------------------- #
# BibTeX / RIS / CSL
# --------------------------------------------------------------------------- #
class CitationFormatsTest(unittest.TestCase):
    def _bm(self, **kw):
        b = Bookmark(url="https://ex.org/a?x=1&y=2", title="Q&A: 50% off #1",
                     date_added=1700000000, browser="F",
                     byline="Ada Lindqvist and Sami Baloch", **kw)
        b.id = 7
        return b

    def test_bibtex_escapes_and_dates(self):
        from chronos.export.exporters import to_bibtex
        b = self._bm(); b.wayback_url = WB
        out = to_bibtex([b])
        self.assertIn(r"title = {Q\&A: 50\% off \#1}", out)
        self.assertIn("author = {Ada Lindqvist and Sami Baloch}", out)
        self.assertIn("url = {https://ex.org/a?x=1&y=2}", out)     # URLs stay verbatim
        self.assertNotIn("date = ", out.replace("urldate", ""))    # bookmarked ≠ published
        self.assertIn(rf"addendum = {{Archived at \url{{{WB}}}}}", out)
        b2 = self._bm(published_ts=1751277600)
        self.assertIn("date = {2025-06-30}", to_bibtex([b2]))

    def test_ris_authors_and_years(self):
        from chronos.export.exporters import to_ris
        b = self._bm(); b.wayback_url = WB
        out = to_ris([b])
        self.assertIn("AU  - Ada Lindqvist\nAU  - Sami Baloch", out)
        self.assertNotIn("PY  -", out)
        self.assertIn(f"L2  - {WB}", out)

    def test_csl_video(self):
        from chronos.interop import bookmark_to_csl
        b = self._bm(kind="video")
        self.assertEqual(bookmark_to_csl(b)["type"], "motion_picture")


# --------------------------------------------------------------------------- #
# GUI: one "Send to" place
# --------------------------------------------------------------------------- #
try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class SendToMenuTest(unittest.TestCase):
    def test_send_to_submenu(self):
        app = QApplication.instance() or QApplication([])  # noqa: F841
        tmp, ctx, *_ = _ctx()
        try:
            from chronos.gui.main_window import MainWindow
            w = MainWindow(ctx)
            sub = w._menus["menu.send_to"]
            labels = [a.text().replace("&", "") for a in sub.actions()]
            self.assertEqual(labels, ["Zotero", "Nawishtar Reading folder…",
                                      "Khwānōk reading book (EPUB)…", "ytman (videos)…"])
            self.assertIn(sub.menuAction(), w._items_menu.actions())
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
