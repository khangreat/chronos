"""v0.30 "Exports, read fully": whole Reddit / X / Mastodon / Facebook exports as
zip or folder, Bluesky's own .car repository, and clear errors for wrong files.

The Bluesky fixture is a genuine CAR v1 repository built here with an
independent DAG-CBOR encoder, sha2-256 CIDs and a two-level Merkle Search Tree
(prefix-compressed keys and a subtree), so the reader is tested against the
real format.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.importers.platform.atproto_car import read_repo  # noqa: E402
from chronos.importers.platform.reddit import parse_reddit_export  # noqa: E402


# --------------------------------------------------------------------------- #
# Independent DAG-CBOR / CID / CAR writer (test-only)
# --------------------------------------------------------------------------- #
class Link(bytes):
    pass


def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    for info, fmt in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
        if n < 1 << (8 * struct.calcsize(fmt)):
            return bytes([major << 5 | info]) + struct.pack(fmt, n)
    raise ValueError


def cbor(v) -> bytes:
    if isinstance(v, Link):
        return b"\xd8\x2a" + _head(2, len(v) + 1) + b"\x00" + bytes(v)
    if v is None:
        return b"\xf6"
    if v is True:
        return b"\xf5"
    if v is False:
        return b"\xf4"
    if isinstance(v, int):
        return _head(0, v) if v >= 0 else _head(1, -1 - v)
    if isinstance(v, bytes):
        return _head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode(); return _head(3, len(b)) + b
    if isinstance(v, list):
        return _head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):   # DAG-CBOR key order: length, then bytes
        keys = sorted(v, key=lambda k: (len(k.encode()), k.encode()))
        return _head(5, len(v)) + b"".join(cbor(k) + cbor(v[k]) for k in keys)
    raise TypeError(type(v))


def cid_for(block: bytes) -> Link:
    return Link(b"\x01\x71\x12\x20" + hashlib.sha256(block).digest())


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def build_car(did: str, records: dict) -> bytes:
    """records: {"collection/rkey": record}. Two-level MST to exercise subtrees."""
    blocks = {}

    def put(obj):
        b = cbor(obj); c = cid_for(b); blocks[bytes(c)] = b; return c

    keys = sorted(records)
    rec_cids = {k: put(records[k]) for k in keys}

    def node(ks, left=None):
        entries, prev = [], b""
        for k in ks:
            kb = k.encode()
            p = 0
            while p < min(len(prev), len(kb)) and prev[p] == kb[p]:
                p += 1
            entries.append({"p": p, "k": kb[p:], "v": rec_cids[k], "t": None})
            prev = kb
        return put({"l": left, "e": entries})

    half = len(keys) // 2
    leaf = node(keys[:half])                       # left subtree
    root = node(keys[half:], left=leaf)
    commit = put({"did": did, "version": 3, "data": root, "rev": "x",
                  "prev": None, "sig": b"\x00" * 8})
    header = cbor({"roots": [commit], "version": 1})
    out = bytearray(varint(len(header)) + header)
    for c, b in blocks.items():
        out += varint(len(c) + len(b)) + c + b
    return bytes(out)


DID = "did:plc:testuser123"
BSKY_RECORDS = {
    "app.bsky.feed.post/3kaaa": {"$type": "app.bsky.feed.post",
                                 "text": "Brahui orthography thread, part one",
                                 "createdAt": "2024-02-01T09:00:00Z"},
    "app.bsky.feed.post/3kaab": {"$type": "app.bsky.feed.post", "text": "part two",
                                 "createdAt": "2024-02-01T09:01:00Z",
                                 "reply": {"root": {"uri": f"at://{DID}/app.bsky.feed.post/3kaaa"},
                                           "parent": {"uri": f"at://{DID}/app.bsky.feed.post/3kaaa"}}},
    "app.bsky.feed.post/3kaac": {"$type": "app.bsky.feed.post", "text": "a good read",
                                 "createdAt": "2024-02-02T10:00:00Z",
                                 "embed": {"$type": "app.bsky.embed.external",
                                           "external": {"uri": "https://example.org/script",
                                                        "title": "Scripts"}}},
    "app.bsky.feed.like/3kzzz": {"$type": "app.bsky.feed.like",
                                 "subject": {"uri": "at://did:plc:other/app.bsky.feed.post/9x",
                                             "cid": "bafy"}, "createdAt": "2024-02-03T00:00:00Z"},
    "app.bsky.actor.profile/self": {"$type": "app.bsky.actor.profile", "displayName": "T"},
}


class CarReaderTest(unittest.TestCase):
    def test_reads_every_record_through_the_tree(self):
        did, recs = read_repo(build_car(DID, BSKY_RECORDS))
        self.assertEqual(did, DID)
        self.assertEqual(set(recs), set(BSKY_RECORDS))          # MST walk is complete
        self.assertEqual(recs["app.bsky.feed.post/3kaab"]["reply"]["parent"]["uri"],
                         f"at://{DID}/app.bsky.feed.post/3kaaa")

    def test_rejects_garbage(self):
        from chronos.importers.platform.atproto_car import CarError
        with self.assertRaises((CarError, IndexError)):
            read_repo(b"\x05not a car file at all")


# --------------------------------------------------------------------------- #
def reddit_export(root: Path) -> Path:
    d = root / "reddit-export"; d.mkdir()
    (d / "posts.csv").write_text(
        "id,permalink,date,ip,subreddit,gildings,title,url,body\n"
        "p1,https://www.reddit.com/r/brahui/comments/p1/script_notes/,"
        "2024-03-01 10:00:00 UTC,1.2.3.4,brahui,0,Script notes,"
        "https://www.reddit.com/r/brahui/comments/p1/script_notes/,Notes on Brahui script\n"
        "p2,https://www.reddit.com/r/linguistics/comments/p2/a_link/,"
        "2024-03-02 10:00:00 UTC,1.2.3.4,linguistics,0,A link,"
        "https://example.org/dravidian,\n", encoding="utf-8")
    (d / "comments.csv").write_text(
        "id,permalink,date,ip,subreddit,gildings,link,parent,body,media\n"
        "c1,https://www.reddit.com/r/brahui/comments/p1/script_notes/c1/,"
        "2024-03-01 11:00:00 UTC,1.2.3.4,brahui,0,"
        "https://www.reddit.com/r/brahui/comments/p1/script_notes/,t3_p1,"
        "Replying to my own post,\n", encoding="utf-8")
    (d / "saved_posts.csv").write_text(
        "id,permalink\ns1,https://www.reddit.com/r/AskHistorians/comments/s1/balochistan/\n",
        encoding="utf-8")
    (d / "post_votes.csv").write_text(
        "id,permalink,direction\n"
        "v1,https://www.reddit.com/r/maps/comments/v1/language_map/,up\n"
        "v2,https://www.reddit.com/r/maps/comments/v2/bad_map/,down\n", encoding="utf-8")
    (d / "ip_logs.csv").write_text("date,ip\n2024-01-01,1.2.3.4\n", encoding="utf-8")
    (d / "subscribed_subreddits.csv").write_text("subreddit\nbrahui\n", encoding="utf-8")
    return d


def zip_dir(d: Path) -> Path:
    z = d.with_suffix(".zip")
    with zipfile.ZipFile(z, "w") as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(d))
    return z


class ExportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_exp_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    # -- Reddit ------------------------------------------------------------- #
    def test_reddit_files_recognised_by_columns(self):
        roles = sorted(i.role for i in parse_reddit_export(reddit_export(self.tmp)))
        # ip logs, subscriptions and the downvote are not archived
        self.assertEqual(roles, ["comment", "post", "post", "saved_post", "upvoted"])

    def test_reddit_whole_export_zip(self):
        r = self.ctx.platform_import.import_reddit(zip_dir(reddit_export(self.tmp)))
        self.assertEqual(r.resources, 5)
        post = self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/brahui/comments/p1/script_notes/")
        self.assertEqual(post.title, "Script notes")
        self.assertEqual(post.page_text, "Notes on Brahui script")
        self.assertIn("r/brahui", post.tags)
        # comment keeps its text and replies to the post
        com = self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/brahui/comments/p1/script_notes/c1/")
        self.assertEqual(com.kind, "social_comment")
        self.assertEqual(self.ctx.resources.parent(com.id).id, post.id)
        # a link post links to its page; upvote is a like; downvote skipped
        lp = self.ctx.storage.get_by_url("https://www.reddit.com/r/linguistics/comments/p2/a_link/")
        self.assertIn("https://example.org/dravidian",
                      [b.url for _, b in self.ctx.resources.outgoing(lp.id)])
        self.assertEqual(len(self.ctx.provenance.by_method("platform_liked")), 1)
        self.assertIsNone(self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/maps/comments/v2/bad_map/"))
        self.assertTrue(self.ctx.search.search("Brahui script"))

    def test_reddit_dates_kept(self):
        self.ctx.platform_import.import_reddit(reddit_export(self.tmp))
        post = self.ctx.storage.get_by_url(
            "https://www.reddit.com/r/brahui/comments/p1/script_notes/")
        self.assertEqual((post.dt.year, post.dt.month, post.dt.day), (2024, 3, 1))

    def test_wrong_file_is_refused_and_not_recorded(self):
        junk = self.tmp / "notes.csv"; junk.write_text("a,b\n1,2\n")
        with self.assertRaises(ValueError):
            self.ctx.platform_import.import_reddit(junk)
        with self.assertRaises(FileNotFoundError):
            self.ctx.platform_import.import_reddit(self.tmp / "missing.zip")
        self.assertEqual(self.ctx.provenance.packages(), [])    # no phantom package

    # -- X ------------------------------------------------------------------ #
    def test_x_archive_zip_with_parts_and_likes(self):
        d = self.tmp / "x-archive" / "data"; d.mkdir(parents=True)
        (d / "tweets.js").write_text('window.YTD.tweets.part0 = [{"tweet":{"id_str":"1",'
                                     '"full_text":"root","created_at":"Wed Oct 10 20:19:24 +0000 2018"}}];')
        (d / "tweets-part1.js").write_text('window.YTD.tweets.part1 = [{"tweet":{"id_str":"2",'
                                           '"full_text":"reply","created_at":"Wed Oct 10 20:25:00 +0000 2018",'
                                           '"in_reply_to_status_id_str":"1"}}];')
        (d / "like.js").write_text('window.YTD.like.part0 = [{"like":{"tweetId":"9","fullText":"liked"}}];')
        (d / "account.js").write_text('window.YTD.account.part0 = [];')
        r = self.ctx.platform_import.import_x(zip_dir(self.tmp / "x-archive"))
        self.assertEqual(r.resources, 3)
        t2 = self.ctx.storage.get_by_url("https://twitter.com/i/web/status/2")
        self.assertEqual(self.ctx.resources.parent(t2.id).page_text, "root")
        self.assertEqual(len(self.ctx.provenance.by_method("platform_liked")), 1)

    # -- Mastodon ----------------------------------------------------------- #
    def test_mastodon_zip(self):
        d = self.tmp / "masto"; d.mkdir()
        (d / "outbox.json").write_text(json.dumps({"orderedItems": [
            {"type": "Create", "object": {"type": "Note", "id": "https://m/s/1",
                                          "url": "https://m/@me/1", "content": "<p>hi</p>",
                                          "published": "2024-01-01T10:00:00Z"}}]}))
        (d / "bookmarks.json").write_text(json.dumps({"orderedItems": ["https://m/@x/5"]}))
        r = self.ctx.platform_import.import_mastodon(zip_dir(d))
        self.assertEqual(r.resources, 2)
        self.assertEqual(len(self.ctx.provenance.by_method("platform_saved")), 1)

    # -- Facebook ----------------------------------------------------------- #
    def test_facebook_html_export_explained(self):
        d = self.tmp / "fb-html" / "your_activity_across_facebook" / "posts"
        d.mkdir(parents=True)
        (d / "your_posts_1.html").write_text("<html>posts</html>")
        with self.assertRaises(ValueError) as e:
            self.ctx.platform_import.import_facebook(self.tmp / "fb-html")
        self.assertIn("JSON", str(e.exception))

    def test_facebook_group_posts(self):
        d = self.tmp / "fb" / "your_facebook_activity" / "groups"; d.mkdir(parents=True)
        (d / "your_group_posts_and_comments.json").write_text(json.dumps({"group_posts_v2": [
            {"timestamp": 1700000000, "data": [{"post": "Group note on Brahui"}]}]}))
        r = self.ctx.platform_import.import_facebook(self.tmp / "fb")
        self.assertEqual(r.resources, 1)
        self.assertTrue(self.ctx.search.search("Group note"))

    # -- Bluesky ------------------------------------------------------------ #
    def test_bluesky_car_import(self):
        car = self.tmp / "repo.car"; car.write_bytes(build_car(DID, BSKY_RECORDS))
        r = self.ctx.platform_import.import_bluesky(car)
        self.assertEqual(r.resources, 4)                      # 3 posts + 1 like
        p1 = self.ctx.storage.get_by_url(f"https://bsky.app/profile/{DID}/post/3kaaa")
        p2 = self.ctx.storage.get_by_url(f"https://bsky.app/profile/{DID}/post/3kaab")
        self.assertEqual(self.ctx.resources.parent(p2.id).id, p1.id)
        p3 = self.ctx.storage.get_by_url(f"https://bsky.app/profile/{DID}/post/3kaac")
        self.assertIn("https://example.org/script",
                      [b.url for _, b in self.ctx.resources.outgoing(p3.id)])
        self.assertEqual(len(self.ctx.provenance.by_method("platform_liked")), 1)
        self.assertEqual(p1.dt.year, 2024)
        r2 = self.ctx.platform_import.import_bluesky(car)
        self.assertTrue(r2.already_imported)

    def test_bluesky_bad_car_message(self):
        bad = self.tmp / "broken.car"; bad.write_bytes(b"\x01\x02junk")
        with self.assertRaises(ValueError):
            self.ctx.platform_import.import_bluesky(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
