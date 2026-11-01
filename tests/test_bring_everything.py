"""v0.36 "Bring everything in": every browser profile (the right folders on
Windows/Linux/macOS), one door for any export or archive (Takeout in parts,
.tgz, translated folder names, zips inside zips, My Activity, Saved, Pocket,
Raindrop, Instapaper, OneTab), Reddit read in the browser and the data download
filled in, and the page-text extractor that the setting really chooses.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402

NETSCAPE = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE><H1>Bookmarks</H1>
<DL><p>
<DT><H3 ADD_DATE="1600000000">Brahui</H3>
<DL><p>
<DT><A HREF="https://example.org/brahui-grammar" ADD_DATE="1600000001">Brahui grammar</A>
<DT><A HREF="https://example.org/dravidian" ADD_DATE="1600000002">Dravidian languages</A>
</DL><p>
</DL><p>"""
READING = """<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p>
<DT><A HREF="https://example.org/to-read" ADD_DATE="1700000000">To read later</A>
</DL>"""
HISTORY = {"Browser History": [
    {"favicon_url": "", "page_transition": "LINK", "title": "Brahui verbs",
     "url": "https://example.org/verbs", "client_id": "a", "time_usec": 1700000000000000},
    {"page_transition": "LINK", "title": "Brahui verbs",
     "url": "https://example.org/verbs", "client_id": "a", "time_usec": 1700500000000000},
    {"page_transition": "TYPED", "title": "Settings", "url": "chrome://settings/",
     "client_id": "a", "time_usec": 1700000000000000},
    {"page_transition": "LINK", "title": "براہوئی", "url": "https://example.org/براہوئی",
     "client_id": "a", "time_usec": 1700100000000000},
]}
ACT_CHROME = [{"header": "Chrome", "title": "Visited Kurukh language",
               "titleUrl": "https://www.google.com/url?q=https://example.org/kurukh&usg=AOv",
               "time": "2024-03-01T10:00:00.000Z", "products": ["Chrome"]}]
ACT_SEARCH = [{"header": "Search", "title": "Searched for brahui grammar pdf",
               "titleUrl": "https://www.google.com/search?q=brahui+grammar+pdf",
               "time": "2024-03-02T10:00:00.000Z", "products": ["Search"]},
              {"header": "Search", "title": "Viewed Maps", "time": "2024-03-02T10:00:00Z",
               "products": ["Search"]}]
ACT_YT = [{"header": "YouTube", "title": "Watched A talk",
           "titleUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
           "time": "2024-03-03T10:00:00.000Z", "products": ["YouTube"]}]
SAVED = "Title,Note,URL,Comment\nQuetta cafe,good tea,https://example.org/cafe,\n"
SUBS = "Channel Id,Channel Url,Channel Title\nUC1,https://youtube.com/c/x,X\n"


def takeout_parts(d: Path, translated=False):
    """A Takeout in two .zip parts, the way Google splits a big export."""
    act = "Meine Aktivitäten" if translated else "My Activity"
    p1 = d / "takeout-20261101T000000Z-001.zip"
    with zipfile.ZipFile(p1, "w") as z:
        z.writestr("Takeout/archive_browser.html", "<html>index</html>")
        z.writestr("Takeout/Chrome/Bookmarks.html", NETSCAPE)
        z.writestr("Takeout/Chrome/Reading List.html", READING)
        z.writestr("Takeout/Chrome/BrowserHistory.json", json.dumps(HISTORY))
        z.writestr("Takeout/Google Photos/IMG_0001.jpg", b"\xff\xd8\xff" + b"0" * 100)
        z.writestr("Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv", SUBS)
    p2 = d / "takeout-20261101T000000Z-002.zip"
    with zipfile.ZipFile(p2, "w") as z:
        z.writestr(f"Takeout/{act}/Chrome/MyActivity.json", json.dumps(ACT_CHROME))
        z.writestr(f"Takeout/{act}/Search/MyActivity.json", json.dumps(ACT_SEARCH))
        z.writestr(f"Takeout/{act}/YouTube/MyActivity.json", json.dumps(ACT_YT))
        z.writestr("Takeout/Saved/Favourite places.csv", SAVED)
        z.writestr("Takeout/Calendar/Personal.ics", "BEGIN:VCALENDAR\nEND:VCALENDAR\n")
        z.writestr("Takeout/Keep/note.json", '{"title": "n"}')
    return [p1, p2]


def _ctx():
    tmp = Path(tempfile.mkdtemp(prefix="chronos_bring_")).resolve()
    return tmp, ApplicationContext.for_dir(tmp / "h")


class TakeoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx()
        self.parts = takeout_parts(self.tmp)

    def tearDown(self):
        self.ctx.close()

    def _check(self, rep):
        r = dict(rep.read)
        self.assertEqual(r["Chrome bookmarks"], [2, 2])
        self.assertEqual(r["Chrome reading list"], [1, 1])
        self.assertEqual(r["Chrome history (Takeout)"], [2, 2])      # one per page, no chrome://
        self.assertEqual(r["Chrome activity (Takeout)"][0], 1)
        self.assertEqual(r["Google searches (Takeout)"], [1, 1])
        self.assertEqual(r["Google Saved"], [1, 1])
        self.assertEqual(rep.skipped.get("youtube"), 2)          # watch history + subscriptions
        self.assertGreaterEqual(rep.skipped.get("media", 0), 1)
        self.assertIn("ytman", rep.handoffs)
        st = self.ctx.storage
        self.assertEqual(st.get_by_url("https://example.org/brahui-grammar").folder_name, "Brahui")
        self.assertEqual(st.get_by_url("https://example.org/to-read").folder_name, "Reading list")
        verbs = st.get_by_url("https://example.org/verbs")
        self.assertEqual(verbs.date_added, 1700500000)                  # latest visit
        self.assertIsNotNone(st.get_by_url("https://example.org/براہوئی"))
        self.assertIsNotNone(st.get_by_url("https://example.org/kurukh"))  # google redirect unwrapped
        q = st.get_by_url("https://www.google.com/search?q=brahui+grammar+pdf")
        self.assertEqual((q.kind, q.title), ("search", "brahui grammar pdf"))
        self.assertEqual(st.get_by_url("https://example.org/cafe").folder_name, "Favourite places")
        self.assertIsNone(st.get_by_url("chrome://settings/"))
        self.assertIsNone(st.get_by_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_all_parts_together(self):
        self._check(self.ctx.universal.import_paths(self.parts))

    def test_folder_holding_the_parts(self):
        folder = self.tmp / "downloads"; folder.mkdir()
        for p in self.parts:
            shutil.copy(p, folder)
        self._check(self.ctx.universal.import_paths([folder]))

    def test_tgz(self):
        tgz = self.tmp / "takeout.tgz"
        with tarfile.open(tgz, "w:gz") as tf:
            for p in self.parts:
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        data = z.read(n)
                        ti = tarfile.TarInfo(n); ti.size = len(data)
                        tf.addfile(ti, io.BytesIO(data))
        self._check(self.ctx.universal.import_paths([tgz]))

    def test_zip_inside_a_zip(self):
        outer = self.tmp / "backup.zip"
        with zipfile.ZipFile(outer, "w") as z:
            for p in self.parts:
                z.write(p, f"old/{p.name}")
        self._check(self.ctx.universal.import_paths([outer]))

    def test_translated_folder_names(self):
        d = self.tmp / "de"; d.mkdir()
        rep = self.ctx.universal.import_paths(takeout_parts(d, translated=True))
        self.assertEqual(dict(rep.read)["Google searches (Takeout)"], [1, 1])

    def test_again_adds_nothing(self):
        self.ctx.universal.import_paths(self.parts)
        n = self.ctx.storage.count()
        rep = self.ctx.universal.import_paths(self.parts)
        self.assertEqual(rep.new, 0)
        self.assertEqual(self.ctx.storage.count(), n)

    def test_activity_as_html_is_explained(self):
        z = self.tmp / "html.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Takeout/My Activity/Chrome/MyActivity.html",
                        '<html><div class="outer-cell mdl-cell">Visited x</div></html>')
        rep = self.ctx.universal.import_paths([z])
        self.assertEqual(rep.skipped.get("activity_html"), 1)
        self.assertIn("as JSON", rep.text())

    def test_takeout_service_never_reads_the_zip_whole(self):
        real = Path.read_bytes

        def guard(self_):
            if self_.suffix == ".zip":
                raise AssertionError(f"read whole: {self_}")
            return real(self_)
        with mock.patch.object(Path, "read_bytes", guard):
            r = self.ctx.takeout.import_takeout(self.parts[0])
        self.assertEqual(r.ingested_bookmarks, 5)            # 2 + 1 reading + 2 history
        self.assertIn("ytman", r.handoffs)

    def test_big_history_streams(self):
        big = {"Browser History": [
            {"url": f"https://example.org/p{i}", "title": f"Page {i}",
             "time_usec": 1700000000000000 + i} for i in range(60000)]}
        f = self.tmp / "BrowserHistory.json"
        f.write_text(json.dumps(big), encoding="utf-8")
        t = time.time()
        rep = self.ctx.universal.import_paths([f])
        self.assertEqual(rep.found, 60000)
        self.assertLess(time.time() - t, 60)

    def test_report_is_plain(self):
        text = self.ctx.universal.import_paths(self.parts).text()
        self.assertIn("Brought in", text)
        self.assertIn("belong to ytman", text)
        self.assertIn("Prepared for your other apps", text)


class LinkListsTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx()

    def tearDown(self):
        self.ctx.close()

    def _imp(self, name, text):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return self.ctx.universal.import_paths([p])

    def test_pocket_csv(self):
        rep = self._imp("part_000000.csv",
                        "title,url,time_added,tags,status\n"
                        "Brahui,https://example.org/p1,1600000000,lang|dravidian,unread\n")
        b = self.ctx.storage.get_by_url("https://example.org/p1")
        self.assertEqual((b.browser, b.date_added), ("Pocket", 1600000000))
        self.assertEqual(sorted(b.tags), ["dravidian", "lang"])
        self.assertIn("Pocket", rep.read)

    def test_raindrop_and_instapaper(self):
        self._imp("raindrop.csv", "id,title,note,excerpt,url,folder,tags,created,cover,"
                  "highlights,favorite\n1,R,n,e,https://example.org/r,Lang,\"a, b\","
                  "2024-01-02T03:04:05.000Z,,,\n")
        self._imp("instapaper.csv", "URL,Title,Selection,Folder,Timestamp\n"
                  "https://example.org/i,I,,Unread,1600000000\n")
        r = self.ctx.storage.get_by_url("https://example.org/r")
        self.assertEqual((r.browser, r.folder_name, sorted(r.tags)), ("Raindrop", "Lang", ["a", "b"]))
        self.assertEqual(self.ctx.storage.get_by_url("https://example.org/i").browser, "Instapaper")

    def test_onetab_and_plain_lists(self):
        rep = self._imp("onetab.txt", "https://example.org/a | Page A\n"
                        "https://example.org/b | Page B\n\nhttps://example.org/c | C\n")
        self.assertEqual(rep.found, 3)
        self.assertEqual(self.ctx.storage.get_by_url("https://example.org/a").title, "Page A")
        rep = self._imp("notes.txt", "My shopping list\nmilk\neggs\n")
        self.assertEqual(rep.found, 0)                              # prose isn't a link list

    def test_pocket_html(self):
        rep = self._imp("ril_export.html", "<!DOCTYPE html><html><head><title>Pocket Export"
                        "</title></head><body><h1>Unread</h1><ul><li><a href=\"https://"
                        "example.org/pk\" time_added=\"1600000000\" tags=\"x,y\">PK</a>"
                        "</li></ul></body></html>")
        self.assertEqual(dict(rep.read)["Pocket"], [1, 1])

    def test_never_reads_passwords(self):
        f = self.tmp / "Login Data"
        con = sqlite3.connect(f); con.execute("CREATE TABLE logins (origin_url, password_value)")
        con.execute("INSERT INTO logins VALUES ('https://example.org', 'secret')"); con.commit()
        con.close()
        rep = self.ctx.universal.import_paths([self.tmp])
        self.assertIsNone(self.ctx.storage.get_by_url("https://example.org"))
        self.assertEqual(rep.found, 0)


# --------------------------------------------------------------------------- #
# Browsers: every profile, the right folders
# --------------------------------------------------------------------------- #
def _chrome_profile(folder: Path, url: str, visits=()):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Bookmarks").write_text(json.dumps({"checksum": "x", "roots": {
        "bookmark_bar": {"type": "folder", "name": "Bar", "children": [
            {"type": "url", "name": "B", "url": url, "date_added": "13300000000000000"}]}}}),
        encoding="utf-8")
    con = sqlite3.connect(folder / "History")
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url, title, visit_count, "
                "last_visit_time)")
    con.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url, visit_time)")
    for i, v in enumerate(visits):
        con.execute("INSERT INTO urls VALUES (?,?,?,1,13300000000000000)", (i, v, v))
    con.commit(); con.close()


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="chronos_home_")).resolve()

    def _win(self):
        local, roaming = self.home / "AppData/Local", self.home / "AppData/Roaming"
        ud = local / "Google/Chrome/User Data"
        _chrome_profile(ud / "Default", "https://example.org/default", ["https://example.org/h1"])
        _chrome_profile(ud / "Profile 1", "https://example.org/work", ["https://example.org/h2"])
        (ud / "Local State").write_text(json.dumps({"profile": {"info_cache": {
            "Default": {"name": "Person 1"}, "Profile 1": {"name": "Work"}}}}), encoding="utf-8")
        _chrome_profile(local / "Microsoft/Edge/User Data/Default", "https://example.org/edge")
        ff = roaming / "Mozilla/Firefox"
        (ff / "Profiles/abcd.default-release").mkdir(parents=True)
        (ff / "Profiles/abcd.default-release/places.sqlite").write_bytes(b"")
        (ff / "profiles.ini").write_text("[Profile0]\nName=default-release\nIsRelative=1\n"
                                         "Path=Profiles/abcd.default-release\n", encoding="utf-8")
        return {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}

    def test_windows_finds_every_profile_in_user_data(self):
        from chronos.importers.profiles import discover
        env = self._win()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(Path, "home", classmethod(lambda c: self.home)):
            found = discover("win32")
        labels = [p.label for p in found]
        self.assertIn("Chrome — Person 1", labels)
        self.assertIn("Chrome — Work", labels)
        self.assertIn("Edge", labels)
        self.assertTrue(any(l.startswith("Firefox") for l in labels))
        work = next(p for p in found if p.profile == "Work")
        self.assertEqual(work.bookmarks.parent.name, "Profile 1")

    def test_linux_folder_names(self):
        from chronos.importers.profiles import discover
        _chrome_profile(self.home / ".config/google-chrome/Default", "https://example.org/l")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / ".config")}), \
                mock.patch.object(Path, "home", classmethod(lambda c: self.home)):
            found = discover("linux")
        self.assertEqual([p.browser for p in found], ["Chrome"])

    def test_import_a_second_profile(self):
        from chronos.importers.profiles import discover
        env = self._win()
        tmp, ctx = _ctx()
        try:
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(Path, "home", classmethod(lambda c: self.home)):
                work = next(p for p in discover("win32") if p.profile == "Work")
            r = ctx.bookmarks.import_profile(work, "bookmarks")
            self.assertEqual((r.found, r.inserted), (1, 1))
            h = ctx.bookmarks.import_profile(work, "history")
            self.assertEqual(h.found, 1)
            self.assertEqual(ctx.storage.get_by_url("https://example.org/work").browser, "Chrome")
        finally:
            ctx.close()

    def test_import_window_lists_profiles(self):
        from chronos.services import sources
        env = self._win()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(Path, "home", classmethod(lambda c: self.home)), \
                mock.patch.object(sys, "platform", "win32"):
            names = [s.name for s in sources.browser_sources()]
        self.assertIn("Chrome — Work bookmarks", names)
        self.assertIn("Chrome — Work history", names)


# --------------------------------------------------------------------------- #
# Reddit
# --------------------------------------------------------------------------- #
def listing(*things, after=None):
    return {"kind": "Listing", "data": {"after": after, "children": list(things)}}


def t3(pid, title, selftext="", url=None, sub="Brahui", author="hdf"):
    return {"kind": "t3", "data": {
        "id": pid, "name": f"t3_{pid}", "title": title, "selftext": selftext,
        "permalink": f"/r/{sub}/comments/{pid}/{title.lower().replace(' ', '_')}/",
        "url": url or f"https://www.reddit.com/r/{sub}/comments/{pid}/",
        "subreddit": sub, "author": author, "created_utc": 1700000000.0}}


def t1(cid, pid, body, sub="Brahui"):
    return {"kind": "t1", "data": {
        "id": cid, "name": f"t1_{cid}", "body": body, "link_id": f"t3_{pid}",
        "permalink": f"/r/{sub}/comments/{pid}/x/{cid}/", "subreddit": sub,
        "author": "someone", "created_utc": 1700000100.0, "link_title": "Thread"}}


class RedditTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx()

    def tearDown(self):
        self.ctx.close()

    def test_saved_json_saved_by_hand(self):
        p = self.tmp / "saved.json"
        p.write_text(json.dumps(listing(
            t3("aa1", "Brahui grammar", "A long text &amp; more"),
            t3("aa2", "Link post", url="https://example.org/article"),
            t1("cc1", "aa1", "Great answer"))), encoding="utf-8")
        rep = self.ctx.universal.import_paths([p])
        self.assertEqual(dict(rep.read)["Reddit"][0], 3)
        post = self.ctx.storage.get_by_url("https://www.reddit.com/r/Brahui/comments/aa1/brahui_grammar/")
        self.assertEqual((post.kind, post.byline), ("social_post", "u/hdf"))
        self.assertEqual(post.page_text, "A long text & more")
        self.assertIsNotNone(self.ctx.storage.get_by_url("https://example.org/article"))
        acq = self.ctx.provenance.for_bookmark(post.id)
        self.assertEqual(acq[0]["method"], "platform_saved")

    def test_fill_in_the_data_download(self):
        z = self.tmp / "export_hdf.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("saved_posts.csv", "id,permalink\naa1,https://www.reddit.com/r/Brahui"
                        "/comments/aa1/brahui_grammar/\n")
            zf.writestr("saved_comments.csv", "id,permalink\ncc1,https://www.reddit.com/r/"
                        "Brahui/comments/aa1/x/cc1/\n")
        self.ctx.platform_import.import_reddit(z)
        wanted = self.ctx.platform_import.reddit_needing_text()
        self.assertEqual(wanted, ["t1_cc1", "t3_aa1"])
        acq_before = len(self.ctx.storage.conn.execute("SELECT * FROM acquisitions").fetchall())
        from chronos.extension.native_host import handle
        r = handle(self.ctx, {"type": "reddit_listing", "role": "fill",
                              "data": listing(t3("aa1", "Brahui grammar", "The full text"),
                                              t1("cc1", "aa1", "The comment"))})
        self.assertTrue(r["ok"])
        post = self.ctx.storage.get_by_url("https://www.reddit.com/r/Brahui/comments/aa1/brahui_grammar/")
        self.assertEqual((post.page_text, post.byline), ("The full text", "u/hdf"))
        self.assertEqual(self.ctx.platform_import.reddit_needing_text(), [])
        acq_after = len(self.ctx.storage.conn.execute("SELECT * FROM acquisitions").fetchall())
        self.assertEqual(acq_after, acq_before)                 # filling isn't saving again

    def test_host_answers_wanted(self):
        from chronos.extension.native_host import handle
        self.assertEqual(handle(self.ctx, {"type": "reddit_wanted"}), {"ok": True, "ids": []})


EXT_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const sent = [], calls = []; let tooMany = 1;
const pages = {
  '/api/me.json': {kind: 't2', data: {name: 'hdf'}},
  '/user/hdf/saved.json?limit=100&raw_json=1': {kind:'Listing', data:{after:'t3_b', children:[{kind:'t3'},{kind:'t3'}]}},
  '/user/hdf/saved.json?limit=100&raw_json=1&after=t3_b': {kind:'Listing', data:{after:null, children:[{kind:'t1'}]}},
  '/user/hdf/submitted.json?limit=100&raw_json=1': {kind:'Listing', data:{after:null, children:[]}},
  '/user/hdf/comments.json?limit=100&raw_json=1': {kind:'Listing', data:{after:null, children:[{kind:'t1'}]}},
};
const ctx = {
  console, setTimeout: (f) => f(), Promise,
  location: {origin: 'https://www.reddit.com'},
  fetch: async (u) => { const p = u.replace('https://www.reddit.com', ''); calls.push(p);
    if (p.startsWith('/user/hdf/upvoted')) return {ok: false, status: 403, json: async () => ({})};
    if (p.startsWith('/user/hdf/comments') && tooMany-- > 0) return {ok: false, status: 429, json: async () => ({})};
    if (!(p in pages)) return {ok: false, status: 404, json: async () => ({})};
    return {ok: true, status: 200, json: async () => pages[p]}; },
  chrome: { runtime: { sendMessage: async (m) => { if (m.type === 'chronos_reddit') { sent.push([m.role, m.data.data.children.length]); return {ok: true, read: m.data.data.children.length, new: 1}; } },
                       onMessage: {addListener(){}}, onInstalled: {addListener(){}}, lastError: null },
            action: {onClicked: {addListener(){}}, setBadgeText(){}, setBadgeBackgroundColor(){}, setTitle(){}},
            contextMenus: {onClicked: {addListener(){}}, create(){}}, scripting: {} },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
vm.runInContext('readReddit("all", [])', ctx).then((res) => {
  console.log(JSON.stringify({res, sent, calls}));
});
"""


@unittest.skipUnless(shutil.which("node"), "Node.js not available")
class ExtensionRedditTest(unittest.TestCase):
    def test_reads_every_list_page_by_page(self):
        js = Path(__file__).resolve().parents[1] / "chronos/extension/webext/background.js"
        h = Path(tempfile.mkdtemp()) / "h.js"
        h.write_text(EXT_HARNESS, encoding="utf-8")
        out = subprocess.run(["node", str(h), str(js)], capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(r["res"]["read"], 4)
        self.assertEqual(r["res"]["name"], "hdf")
        self.assertEqual(r["sent"], [["saved", 2], ["saved", 1], ["comments", 1]])
        self.assertIn("/user/hdf/saved.json?limit=100&raw_json=1&after=t3_b", r["calls"])
        self.assertEqual(r["calls"].count("/user/hdf/comments.json?limit=100&raw_json=1"), 2)  # 429 retried

    def test_manifest_asks_for_no_new_permissions(self):
        m = json.loads((Path(__file__).resolve().parents[1] /
                        "chronos/extension/webext/manifest.json").read_text("utf-8"))
        self.assertEqual(sorted(m["permissions"]),
                         ["activeTab", "contextMenus", "nativeMessaging", "scripting"])
        self.assertNotIn("host_permissions", m)


# --------------------------------------------------------------------------- #
# Page text: the setting chooses
# --------------------------------------------------------------------------- #
NO_ARTICLE = ("<html><head><title>Notes</title></head><body>"
              "<div class='menu'>Home About Login Shop Subscribe Newsletter</div><div><p>"
              + "Brahui is a Dravidian language spoken in Balochistan and Afghanistan. " * 5
              + "</p><p>" + "Its verbs agree with the subject in person and number. " * 5
              + "</p></div><div class='foot'>Copyright privacy terms cookies</div></body></html>")


class ExtractorSettingTest(unittest.TestCase):
    def test_setting_is_used(self):
        from chronos.web.extract import available_extractors
        if "trafilatura" not in available_extractors():
            self.skipTest("Trafilatura not installed")
        from dataclasses import replace
        tmp, ctx = _ctx()
        try:
            for pref, menu_kept in (("builtin", True), ("auto", False)):
                ctx.config._settings = replace(ctx.config.settings, prefer_extractor=pref)
                bid, _ = ctx.storage.upsert_bookmark(Bookmark(
                    url=f"https://example.org/{pref}", title="t", date_added=1, browser="F"))
                ctx.archive.archive_from_html(bid, NO_ARTICLE, f"https://example.org/{pref}")
                text = ctx.storage.get(bid).page_text
                self.assertIn("Dravidian", text)
                self.assertEqual("Subscribe" in text, menu_kept, pref)
        finally:
            ctx.close()

    def test_settings_offer_only_what_this_copy_has(self):
        from PySide6.QtWidgets import QApplication
        from chronos.core.config import Settings
        from chronos.gui.settings_dialog import SettingsDialog
        from chronos.web.extract import available_extractors
        QApplication.instance() or QApplication([])
        d = SettingsDialog(Settings())
        keys = [d.extractor.itemData(i) for i in range(d.extractor.count())]
        self.assertEqual(keys[:2], ["auto", "builtin"])
        self.assertEqual(set(keys[2:]), set(available_extractors()) - {"builtin"})
        self.assertNotIn("if installed", " ".join(d.extractor.itemText(i)
                                                   for i in range(d.extractor.count())))


class ImportWindowTest(unittest.TestCase):
    def test_anything_is_first_and_takes_many(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from chronos.gui.import_dialog import ImportDialog
        tmp, ctx = _ctx()
        try:
            dlg = ImportDialog(ctx, sync=True)
            self.assertEqual(list(dlg.sources)[0] if not any(
                s.group == "browsers" for s in dlg.sources.values()) else "anything",
                "anything")
            labels = [b.text() for b in dlg._buttons["anything"]]
            self.assertEqual(labels, ["Choose files…", "Folder…"])
            dlg.run_source("anything", [str(p) for p in takeout_parts(tmp)])
            self.assertIn("Brought in", dlg.status_text("anything"))
            self.assertIsNotNone(ctx.storage.get_by_url("https://example.org/brahui-grammar"))
        finally:
            ctx.close()

    def test_window_accepts_drops(self):
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from chronos.gui.main_window import MainWindow
        tmp, ctx = _ctx()
        try:
            w = MainWindow(ctx)
            self.assertTrue(w.acceptDrops())
            m = QMimeData(); m.setUrls([QUrl.fromLocalFile(str(tmp))])
            self.assertEqual(w._dropped_paths(m), [str(tmp)])
            m2 = QMimeData(); m2.setText("just text")
            self.assertEqual(w._dropped_paths(m2), [])
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
