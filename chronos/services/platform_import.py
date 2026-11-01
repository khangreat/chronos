"""PlatformImportService — ingest account-export packages into Chronos.

A platform import is a DataPackage (the original file, hashed and recorded) plus
normalized resources plus a `platform_saved` acquisition per resource linking
back to the package. Re-importing the same file is a no-op (same hash); a newer
export (different hash) records a fresh acquisition occurrence on resources that
persist, so the chronology of how an item kept appearing is preserved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..core.models import Bookmark
from ..importers.platform.bluesky import parse_bluesky
from ..importers.platform.facebook import parse_facebook
from ..importers.platform.mastodon import parse_collection_urls, parse_outbox
from ..importers.platform.reddit import parse_reddit_csv
from ..importers.platform.twitter import parse_likes, parse_tweets

PARSER_VERSION = "reddit-2"


def _must_exist(path) -> Path:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} doesn\u2019t exist.")
    return path
X_PARSER_VERSION = "x-1"
MASTODON_PARSER_VERSION = "mastodon-1"
BLUESKY_PARSER_VERSION = "bluesky-1"
FACEBOOK_PARSER_VERSION = "facebook-1"


@dataclass
class ImportResult:
    provider: str
    package_id: int
    already_imported: bool
    resources: int
    new_resources: int
    acquisitions: int


class PlatformImportService:
    def __init__(self, ctx):
        self.ctx = ctx

    def import_reddit_csv(self, path, kind: str = "post",
                          retain: bool = True) -> ImportResult:
        """One saved_posts.csv / saved_comments.csv (kept for compatibility)."""
        return self.import_reddit(path, single_kind=kind, retain=retain)

    def import_reddit(self, path, single_kind=None, retain: bool = True) -> ImportResult:
        """A Reddit data export — the .zip, the unzipped folder, or one CSV.
        Your posts and comments (with their text), saved items, and upvotes."""
        from ..importers.platform._archive import hash_path
        from ..importers.platform.reddit import parse_reddit_export
        path = _must_exist(path)
        items = parse_reddit_export(path, single_kind=single_kind)
        if not items:
            raise ValueError(
                "No Reddit posts, comments or saved items were found. Choose the "
                ".zip from Reddit\u2019s data download, its folder, or a CSV such as "
                "saved_posts.csv.")
        sha = hash_path(path)
        pkg_id, seen = self.ctx.provenance.register_package(
            "reddit", source_filename=path.name, archive_hash=sha,
            parser_version=PARSER_VERSION,
            retained_path=str(path) if retain else None)
        fallback_ts = int(path.stat().st_mtime) if path.exists() else 0
        new, acq = self._store_reddit(items, pkg_id, fallback_ts)
        self.ctx.storage.update_package_count(pkg_id, len(items))
        return ImportResult("reddit", pkg_id, seen, len(items), new, acq)

    def import_reddit_items(self, items, label: str = "reddit.com") -> ImportResult:
        """Reddit items read in the browser (extension) or saved as .json from
        reddit.com. Items marked "fill" complete ones from the data download."""
        import hashlib
        import time
        items = list(items)
        if not items:
            raise ValueError("No Reddit posts or comments in that.")
        sha = hashlib.sha256("|".join(sorted(f"{i.role}:{i.platform_id}" for i in items))
                             .encode()).hexdigest()
        pkg_id, seen = self.ctx.provenance.register_package(
            "reddit", source_filename=label, archive_hash=sha,
            parser_version=PARSER_VERSION, retained_path=None)
        new, acq = self._store_reddit(items, pkg_id, int(time.time()))
        self.ctx.storage.update_package_count(pkg_id, len(items))
        return ImportResult("reddit", pkg_id, seen, len(items), new, acq)

    def reddit_needing_text(self, limit: int = 20000):
        """Reddit fullnames (t3_abc, t1_def) of items from the data download that
        have no text yet — for the extension to fill in."""
        rows = self.ctx.storage.conn.execute(
            """SELECT DISTINCT a.detail, b.kind FROM acquisitions a
               JOIN bookmarks b ON b.id = a.bookmark_id
               WHERE a.source = 'reddit' AND (b.page_text IS NULL OR b.page_text = '')
               AND a.detail IS NOT NULL LIMIT ?""", (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["detail"])
            except (TypeError, ValueError):
                continue
            pid = (d.get("id") or "").strip()
            if pid and "_" not in pid:
                out.append(("t1_" if r["kind"] == "social_comment" else "t3_") + pid)
            elif pid:
                out.append(pid)
        return sorted(set(out))

    def _store_reddit(self, items, pkg_id, fallback_ts):
        new = acq = 0
        method = {"post": "imported", "comment": "imported",
                  "saved_post": "platform_saved", "saved_comment": "platform_saved",
                  "upvoted": "platform_liked"}
        comments = []
        for it in items:
            # "fill" items complete ones already here (titles and text that
            # Reddit's data download leaves out); new ones count as saved.
            fill = it.role.startswith("fill_")
            role = {"fill_post": "saved_post", "fill_comment": "saved_comment"}.get(
                it.role, it.role)
            kind = ("social_comment" if role in ("comment", "saved_comment")
                    else "social_post")
            author = getattr(it, "author", "") or ""
            byline = f"u/{author}" if author and author != "[deleted]" else None
            bm = self.ctx.storage.get_by_url(it.url)
            if bm is None:
                bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                    url=it.url, title=it.title,
                    date_added=it.timestamp or fallback_ts, browser="Reddit",
                    site_name="Reddit", kind=kind, page_text=it.text or None,
                    byline=byline, published_ts=it.timestamp))
                new += 1
            else:
                bid = bm.id
                self.ctx.storage.set_kind(bid, kind)
                if it.text and not bm.page_text:
                    self.ctx.storage.conn.execute(
                        "UPDATE bookmarks SET page_text=?, title=? WHERE id=?",
                        (it.text, it.title, bid))
                if byline and not bm.byline:
                    self.ctx.storage.conn.execute(
                        "UPDATE bookmarks SET byline=?, published_ts=COALESCE(published_ts, ?) "
                        "WHERE id=?", (byline, it.timestamp, bid))
                self.ctx.storage.conn.commit()
            if (not fill or bm is None) and self.ctx.provenance.record(
                    bid, method[role], source="reddit", package_id=pkg_id,
                    detail={"id": it.platform_id, "role": role}):
                acq += 1
            if it.subreddit:
                cur = self.ctx.storage.get(bid).tags or []
                tag = f"r/{it.subreddit}".lower()
                if tag not in cur:
                    self.ctx.storage.set_tags(bid, sorted(set(cur) | {tag}))
            if it.link_url:
                lb = self.ctx.storage.get_by_url(it.link_url)
                if lb is None:
                    lid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                        url=it.link_url, title=it.link_url,
                        date_added=it.timestamp or fallback_ts, browser="Reddit"))
                    new += 1
                else:
                    lid = lb.id
                if lid != bid:
                    self.ctx.resources.relate(bid, lid, "links_to")
            if kind == "social_comment":
                comments.append((bid, it))
        # second pass: every post is in now, so comments can find their thread
        for bid, it in comments:
            thread = self.ctx.storage.get_by_url(it.thread_url) if it.thread_url else None
            if thread is not None and thread.id != bid:
                self.ctx.resources.relate(bid, thread.id, "reply_to")
            else:
                self._link_to_submission(bid, it.url)
        return new, acq

    @staticmethod
    def _submission_id(url: str):
        parts = [p for p in url.split("/") if p]
        if "comments" in parts:
            i = parts.index("comments")
            if len(parts) > i + 1:
                return parts[i + 1]
        return None

    def _link_to_submission(self, comment_id: int, comment_url: str) -> None:
        """Best-effort: if the comment's submission post is also in the archive,
        record comment reply_to post."""
        sub = self._submission_id(comment_url)
        if not sub:
            return
        for post in self.ctx.storage.find_by_url_pattern(f"%/comments/{sub}/%"):
            if post.id != comment_id and post.kind == "social_post":
                self.ctx.resources.relate(comment_id, post.id, "reply_to")
                return

    # -- X (Twitter) -------------------------------------------------------- #
    def import_x_tweets(self, path, retain: bool = True) -> ImportResult:
        return self.import_x(path, want="tweets", retain=retain)

    def import_x_likes(self, path, retain: bool = True) -> ImportResult:
        return self.import_x(path, want="likes", retain=retain)

    @staticmethod
    def _x_kind(name: str) -> str:
        stem = name.rsplit(".", 1)[0]
        if stem in ("tweets", "tweet") or stem.startswith(("tweets-part", "tweet-part")):
            return "tweets"
        if stem == "like" or stem.startswith("like-part"):
            return "likes"
        return ""

    def import_x(self, path, want: str = "all", retain: bool = True) -> ImportResult:
        """An X archive — the .zip, its folder, or a single tweets.js / like.js.
        Posts (threads rebuilt) and likes."""
        from ..importers.platform._archive import basename, hash_path, iter_files
        path = _must_exist(path)
        single = path.is_file() and path.suffix.lower() == ".js"
        tweets, likes = [], []
        for rel, data in iter_files(path, lambda r: r.endswith(".js")):
            k = self._x_kind(basename(rel))
            if single and not k:          # a lone file: trust the caller's choice
                k = "likes" if want == "likes" else "tweets"
            text = data.decode("utf-8", "replace")
            if k == "tweets" and want in ("all", "tweets"):
                tweets += parse_tweets(text)
            elif k == "likes" and want in ("all", "likes"):
                likes += parse_likes(text)
        if not tweets and not likes:
            raise ValueError(
                "No posts or likes were found. Choose the archive .zip from X, its "
                "folder, or tweets.js / like.js from its data folder.")
        pkg_id, seen = self.ctx.provenance.register_package(
            "x", source_filename=path.name, archive_hash=hash_path(path),
            parser_version=X_PARSER_VERSION,
            retained_path=str(path) if retain else None)
        fallback_ts = int(path.stat().st_mtime)
        id_to_bid, new, acq = {}, 0, 0
        for r in tweets:
            bm = self.ctx.storage.get_by_url(r.url)
            if bm is None:
                bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                    url=r.url, title=r.text and r.text[:70] or f"Post {r.tweet_id}",
                    date_added=r.created_ts or fallback_ts, browser="X",
                    site_name="X", kind="social_post", page_text=r.text))
                new += 1
            else:
                bid = bm.id
                self.ctx.storage.set_kind(bid, "social_post")
            id_to_bid[r.tweet_id] = bid
            if self.ctx.provenance.record(
                    bid, "imported", source="x", package_id=pkg_id,
                    detail={"id": r.tweet_id, "in_reply_to": r.in_reply_to}):
                acq += 1
        for r in tweets:                   # rebuild threads within the archive
            child, parent = id_to_bid.get(r.tweet_id), id_to_bid.get(r.in_reply_to or "")
            if child and parent and child != parent:
                self.ctx.resources.relate(child, parent, "reply_to")
        for r in likes:
            bm = self.ctx.storage.get_by_url(r.url)
            if bm is None:
                bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                    url=r.url, title=r.text and r.text[:70] or f"Post {r.tweet_id}",
                    date_added=fallback_ts, browser="X", site_name="X",
                    kind="social_post", page_text=r.text or None))
                new += 1
            else:
                bid = bm.id
            if self.ctx.provenance.record(
                    bid, "platform_liked", source="x", package_id=pkg_id,
                    detail={"id": r.tweet_id}):
                acq += 1
        total = len(tweets) + len(likes)
        self.ctx.storage.update_package_count(pkg_id, total)
        return ImportResult("x", pkg_id, seen, total, new, acq)

    # -- shared social ingest ---------------------------------------------- #
    def _social_resource(self, url, title, text, author, created_ts, pkg_id,
                         path, method="imported", source="", kind="social_post"):
        bm = self.ctx.storage.get_by_url(url)
        if bm is None:
            bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
                url=url, title=(title or (text or url)[:70]),
                date_added=created_ts or int(Path(path).stat().st_mtime),
                browser=source.capitalize() or "Social",
                site_name=(None if kind == "webpage" else
                           {"mastodon": "Mastodon", "bluesky": "Bluesky",
                            "facebook": "Facebook"}.get(source, source or None)),
                byline=author, page_text=text or None, kind=kind))
            new = True
        else:
            bid = bm.id
            self.ctx.storage.set_kind(bid, kind)
            new = False
        acq = bool(self.ctx.provenance.record(
            bid, method, source=source, package_id=pkg_id,
            detail={"author": author}))
        return bid, new, acq

    # -- Mastodon ----------------------------------------------------------- #
    def import_mastodon(self, path, retain: bool = True) -> ImportResult:
        """A Mastodon archive — the .zip, its folder, or outbox.json. Posts
        (threads rebuilt), plus bookmarks and likes when present."""
        from ..importers.platform._archive import basename, hash_path, iter_files
        path = _must_exist(path)
        files = {}
        for rel, data in iter_files(path, lambda r: r.endswith(".json")):
            name = basename(rel)
            if path.is_file() and path.suffix.lower() == ".json":
                name = "outbox.json"               # a lone file is the outbox
            if name in ("outbox.json", "bookmarks.json", "likes.json"):
                files.setdefault(name, data.decode("utf-8", "replace"))
        posts = parse_outbox(files.get("outbox.json", ""))
        saved = parse_collection_urls(files.get("bookmarks.json", ""))
        liked = parse_collection_urls(files.get("likes.json", ""))
        if not (posts or saved or liked):
            raise ValueError(
                "No posts, bookmarks or likes were found. Choose the archive .zip "
                "from Mastodon, its folder, or outbox.json.")
        pkg_id, seen = self.ctx.provenance.register_package(
            "mastodon", source_filename=path.name, archive_hash=hash_path(path),
            parser_version=MASTODON_PARSER_VERSION,
            retained_path=str(path) if retain else None)
        id_to_bid, new, acq = {}, 0, 0
        for p in posts:
            bid, isnew, gotacq = self._social_resource(
                p.url, None, p.text, p.author, p.created_ts, pkg_id, path,
                method="imported", source="mastodon")
            id_to_bid[p.status_id] = bid
            id_to_bid[p.url] = bid
            new += isnew
            acq += gotacq
        for p in posts:
            if p.in_reply_to and p.in_reply_to in id_to_bid:
                child, parent = id_to_bid.get(p.status_id), id_to_bid[p.in_reply_to]
                if child and parent and child != parent:
                    self.ctx.resources.relate(child, parent, "reply_to")
        for urls, method in ((saved, "platform_saved"), (liked, "platform_liked")):
            for url in urls:
                _, isnew, gotacq = self._social_resource(
                    url, None, None, None, None, pkg_id, path,
                    method=method, source="mastodon")
                new += isnew
                acq += gotacq
        total = len(posts) + len(saved) + len(liked)
        self.ctx.storage.update_package_count(pkg_id, total)
        return ImportResult("mastodon", pkg_id, seen, total, new, acq)

    # -- Bluesky ------------------------------------------------------------ #
    def import_bluesky(self, path, retain: bool = True) -> ImportResult:
        """Bluesky's own export (.car, or a .zip holding one), or a JSON file of
        posts. Posts (threads rebuilt, shared links kept) and likes."""
        from ..importers.platform._archive import hash_path, iter_files
        from ..importers.platform.atproto_car import CarError
        from ..importers.platform.bluesky import parse_bluesky_car
        path = _must_exist(path)
        posts, liked = [], []
        for rel, data in iter_files(path, lambda r: r.endswith((".car", ".json"))):
            if rel.lower().endswith(".car"):
                try:
                    p, l = parse_bluesky_car(data)
                except (CarError, IndexError, KeyError) as e:
                    raise ValueError(f"This .car file couldn\u2019t be read ({e}).")
                posts += p; liked += l
            else:
                posts += parse_bluesky(data.decode("utf-8", "replace"))
        if not posts and not liked:
            raise ValueError(
                "No posts or likes were found. In Bluesky, use Settings, Account, "
                "\u201cExport my data\u201d, and choose the .car file it saves.")
        pkg_id, seen = self.ctx.provenance.register_package(
            "bluesky", source_filename=path.name, archive_hash=hash_path(path),
            parser_version=BLUESKY_PARSER_VERSION,
            retained_path=str(path) if retain else None)
        uri_to_bid, new, acq = {}, 0, 0
        for p in posts:
            bid, isnew, gotacq = self._social_resource(
                p.url, None, p.text, p.author, p.created_ts, pkg_id, path,
                method="imported", source="bluesky")
            uri_to_bid[p.at_uri] = bid
            new += isnew
            acq += gotacq
            if p.shared_url:
                sid, s_new, _ = self._social_resource(
                    p.shared_url, p.shared_url, None, None, p.created_ts, pkg_id,
                    path, method="imported", source="bluesky", kind="webpage")
                new += s_new
                if sid != bid:
                    self.ctx.resources.relate(bid, sid, "links_to")
        for p in posts:
            if p.reply_parent_uri and p.reply_parent_uri in uri_to_bid:
                child, parent = uri_to_bid.get(p.at_uri), uri_to_bid[p.reply_parent_uri]
                if child and parent and child != parent:
                    self.ctx.resources.relate(child, parent, "reply_to")
        for url in liked:
            _, isnew, gotacq = self._social_resource(
                url, "Post you liked on Bluesky", None, None, None, pkg_id, path,
                method="platform_liked", source="bluesky")
            new += isnew
            acq += gotacq
        total = len(posts) + len(liked)
        self.ctx.storage.update_package_count(pkg_id, total)
        return ImportResult("bluesky", pkg_id, seen, total, new, acq)

    # -- Facebook ----------------------------------------------------------- #
    @staticmethod
    def _hash_path(path: Path) -> str:
        h = hashlib.sha256()
        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        else:
            for f in sorted(path.rglob("*.json")):
                h.update(str(f.relative_to(path)).encode())
                h.update(f.read_bytes())
        return h.hexdigest()

    def import_facebook(self, path, retain: bool = True) -> ImportResult:
        """A Facebook 'Download Your Information' export (JSON), as a folder or
        .zip: your posts, saved items and comments."""
        from ..importers.platform._archive import contains, hash_path
        path = _must_exist(path)
        items = parse_facebook(path)
        if not items:
            if contains(path, ".html"):
                raise ValueError(
                    "This is the HTML version of the Facebook download. Request a new "
                    "download in Facebook\u2019s settings and choose the JSON format.")
            raise ValueError(
                "No posts, saved items or comments were found. Choose the .zip from "
                "Facebook\u2019s \u201cDownload your information\u201d, or its folder.")
        pkg_id, seen = self.ctx.provenance.register_package(
            "facebook", source_filename=path.name, archive_hash=hash_path(path),
            parser_version=FACEBOOK_PARSER_VERSION,
            retained_path=str(path) if retain else None)
        new = acq = 0
        anchor = path if path.exists() else Path(".")
        for it in items:
            if it.kind == "saved":
                bid, isnew, got = self._social_resource(
                    it.url, it.title, None, None, it.timestamp, pkg_id, anchor,
                    method="platform_saved", source="facebook", kind="webpage")
            else:
                kind = "social_post" if it.kind == "post" else "social_comment"
                bid, isnew, got = self._social_resource(
                    it.url, it.title, it.text, None, it.timestamp, pkg_id, anchor,
                    method="imported", source="facebook", kind=kind)
                if it.shared_url:
                    sid, s_new, _ = self._social_resource(
                        it.shared_url, it.extra.get("shared_name") or it.shared_url,
                        None, None, it.timestamp, pkg_id, anchor,
                        method="imported", source="facebook", kind="webpage")
                    new += s_new
                    if sid != bid:
                        self.ctx.resources.relate(bid, sid, "links_to")
            new += isnew
            acq += got
        self.ctx.storage.update_package_count(pkg_id, len(items))
        return ImportResult("facebook", pkg_id, seen, len(items), new, acq)
