"""Storage: the only module that talks to SQLite. SQLite is entity truth.

Deliberately no business logic here — services coordinate; storage persists.
All writes go through one connection with foreign keys on and WAL for safety.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from .migrations import apply_migrations, current_target_version, get_db_version
from .models import Bookmark


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.version = apply_migrations(self.conn)

    # -- lifecycle ---------------------------------------------------------- #
    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes ------------------------------------------------------------- #
    def upsert_bookmark(self, bm: Bookmark) -> tuple[int, bool]:
        """Insert, or return existing id if (browser,url) already present.

        Returns (bookmark_id, inserted?). Existing rows are left untouched so a
        re-import never clobbers user edits (favourites/notes/tags).
        """
        if getattr(bm, "kind", "webpage") in ("webpage", "generic"):
            from ..web.video import parse_video
            if parse_video(bm.url):
                bm.kind = "video"
        cur = self.conn.execute(
            "SELECT id FROM bookmarks WHERE browser=? AND url=?",
            (bm.browser, bm.url),
        )
        row = cur.fetchone()
        if row is not None:
            return int(row["id"]), False

        from ..web.sites import domain_of
        cur = self.conn.execute(
            """INSERT INTO bookmarks
               (browser, title, url, date_added, year, month, folder_name,
                page_text, is_favorite, notes,
                page_title, byline, site_name, published_ts, excerpt, kind, domain)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                bm.browser, bm.title, bm.url, bm.date_added, bm.year, bm.month,
                bm.folder_name, bm.page_text, int(bm.is_favorite), bm.notes,
                bm.page_title, bm.byline, bm.site_name, bm.published_ts, bm.excerpt,
                bm.kind, domain_of(bm.url),
            ),
        )
        bid = int(cur.lastrowid)
        if bm.tags:
            self.set_tags(bid, bm.tags, commit=False)
        return bid, True

    def import_bookmarks(self, bookmarks: Iterable[Bookmark]) -> int:
        inserted = 0
        for bm in bookmarks:
            _, was_new = self.upsert_bookmark(bm)
            inserted += int(was_new)
        self.conn.commit()
        return inserted

    # -- tags --------------------------------------------------------------- #
    def _tag_id(self, name: str) -> int:
        name = name.strip()
        self.conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
        return int(self.conn.execute(
            "SELECT id FROM tags WHERE name=?", (name,)
        ).fetchone()["id"])

    def set_tags(self, bookmark_id: int, tags: List[str], commit: bool = True) -> None:
        self.conn.execute(
            "DELETE FROM bookmark_tags WHERE bookmark_id=?", (bookmark_id,)
        )
        for t in {t.strip() for t in tags if t.strip()}:
            self.conn.execute(
                "INSERT OR IGNORE INTO bookmark_tags(bookmark_id, tag_id) VALUES (?,?)",
                (bookmark_id, self._tag_id(t)),
            )
        if commit:
            self.conn.commit()

    def tags_for(self, bookmark_id: int) -> List[str]:
        rows = self.conn.execute(
            """SELECT t.name FROM tags t
               JOIN bookmark_tags bt ON bt.tag_id = t.id
               WHERE bt.bookmark_id=? ORDER BY t.name""",
            (bookmark_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # -- reads -------------------------------------------------------------- #
    def _row_to_bookmark(self, row: sqlite3.Row) -> Bookmark:
        keys = row.keys()

        def g(k):
            return row[k] if k in keys else None

        return Bookmark(
            id=row["id"], browser=row["browser"], title=row["title"], url=row["url"],
            date_added=row["date_added"], folder_name=row["folder_name"],
            page_text=row["page_text"], is_favorite=bool(row["is_favorite"]),
            notes=row["notes"], is_dead=bool(row["is_dead"]),
            wayback_url=row["wayback_url"], tags=self.tags_for(row["id"]),
            page_title=g("page_title"), byline=g("byline"),
            site_name=g("site_name"), published_ts=g("published_ts"),
            excerpt=g("excerpt"), fetched_at=g("fetched_at"), kind=g("kind") or "webpage",
        )

    def _rows_to_bookmarks(self, rows) -> List[Bookmark]:
        """Batch build — ONE tag query for the whole set, not one per row.

        Avoids the N+1 pattern when materialising a period or search result.
        """
        rows = list(rows)
        ids = [r["id"] for r in rows]
        tag_map = self._tags_for_many(ids)
        out: List[Bookmark] = []
        for row in rows:
            keys = row.keys()

            def g(k, _row=row, _keys=keys):
                return _row[k] if k in _keys else None

            out.append(Bookmark(
                id=row["id"], browser=row["browser"], title=row["title"],
                url=row["url"], date_added=row["date_added"],
                folder_name=row["folder_name"], page_text=row["page_text"],
                is_favorite=bool(row["is_favorite"]), notes=row["notes"],
                is_dead=bool(row["is_dead"]), wayback_url=row["wayback_url"],
                tags=tag_map.get(row["id"], []),
                page_title=g("page_title"), byline=g("byline"),
                site_name=g("site_name"), published_ts=g("published_ts"),
                excerpt=g("excerpt"), fetched_at=g("fetched_at"),
                kind=g("kind") or "webpage",
            ))
        return out

    def _tags_for_many(self, ids: List[int]) -> dict:
        if not ids:
            return {}
        out: dict = {}
        # Chunk to stay under SQLite's variable limit on very large sets.
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            ph = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"""SELECT bt.bookmark_id AS bid, t.name AS name
                    FROM bookmark_tags bt JOIN tags t ON t.id = bt.tag_id
                    WHERE bt.bookmark_id IN ({ph})
                    ORDER BY t.name""",
                chunk,
            ).fetchall()
            for r in rows:
                out.setdefault(r["bid"], []).append(r["name"])
        return out

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0])

    def by_year(self, year: int) -> List[Bookmark]:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE year=? ORDER BY date_added DESC", (year,)
        ).fetchall()
        return self._rows_to_bookmarks(rows)

    def by_period(self, year: int, month: int = 0, limit: int = 0,
                  offset: int = 0) -> List[Bookmark]:
        """Load a year (month=0) or a specific month, filtered and paginated in
        SQL — never load a whole year just to slice one month in Python.
        """
        sql = "SELECT * FROM bookmarks WHERE year=?"
        params: list = [year]
        if month:
            sql += " AND month=?"
            params.append(month)
        sql += " ORDER BY date_added DESC"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        return self._rows_to_bookmarks(self.conn.execute(sql, params).fetchall())

    def count_period(self, year: int, month: int = 0) -> int:
        sql = "SELECT COUNT(*) FROM bookmarks WHERE year=?"
        params: list = [year]
        if month:
            sql += " AND month=?"
            params.append(month)
        return int(self.conn.execute(sql, params).fetchone()[0])

    def page_period(self, year: int, month: int = 0, after=None,
                    limit: int = 200):
        """Keyset page of a period ordered by (date_added DESC, id DESC).

        `after` is (date_added, id) of the last row already seen, or None for
        the first page. Keyset paging is O(limit) regardless of how deep you
        scroll — no growing OFFSET scan.
        """
        sql = "SELECT * FROM bookmarks WHERE year=?"
        params: list = [year]
        if month:
            sql += " AND month=?"
            params.append(month)
        if after is not None:
            sql += " AND (date_added < ? OR (date_added = ? AND id < ?))"
            params += [after[0], after[0], after[1]]
        sql += " ORDER BY date_added DESC, id DESC LIMIT ?"
        params.append(limit)
        return self._rows_to_bookmarks(self.conn.execute(sql, params).fetchall())

    def mark_link_status(self, bookmark_id: int, is_dead: bool,
                         checked_ts: int) -> None:
        self.conn.execute(
            "UPDATE bookmarks SET is_dead=?, last_checked=? WHERE id=?",
            (int(is_dead), checked_ts, bookmark_id))
        self.conn.commit()

    # -- sites and fetching ------------------------------------------------- #
    def bookmarks_by_domain(self, domain: str, limit: int = 1000) -> List[Bookmark]:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE domain=? OR domain LIKE ? "
            "ORDER BY date_added DESC LIMIT ?", (domain, f"%.{domain}", limit)).fetchall()
        return self._rows_to_bookmarks(rows)

    def log_fetch(self, bookmark_id: int, status: str, kind: str, code=None,
                  reason: str = "", final_url=None, commit: bool = True) -> None:
        import time as _t
        self.conn.execute(
            """INSERT INTO fetch_log (bookmark_id, status, code, reason, final_url, kind,
                                      attempted_at, attempts)
               VALUES (?,?,?,?,?,?,?,1)
               ON CONFLICT(bookmark_id) DO UPDATE SET status=excluded.status,
                 code=excluded.code, reason=excluded.reason, final_url=excluded.final_url,
                 kind=excluded.kind, attempted_at=excluded.attempted_at,
                 attempts=fetch_log.attempts + 1""",
            (bookmark_id, status, code, reason, final_url, kind, int(_t.time())))
        if commit:
            self.conn.commit()

    def fetch_status(self, bookmark_id: int):
        r = self.conn.execute("SELECT * FROM fetch_log WHERE bookmark_id=?",
                              (bookmark_id,)).fetchone()
        return dict(r) if r else None

    def fetch_status_counts(self) -> dict:
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT status, COUNT(*) FROM fetch_log GROUP BY status")}

    def set_wayback(self, bookmark_id: int, url) -> None:
        self.conn.execute("UPDATE bookmarks SET wayback_url=? WHERE id=?",
                          (url, bookmark_id))
        self.conn.commit()

    # -- archives ----------------------------------------------------------- #
    def add_archive(self, bookmark_id: int, path: str, sha1: str,
                    nbytes: int, archived_at: int, mime: str = "text/html") -> int:
        self.conn.execute(
            """INSERT INTO archives(bookmark_id, path, sha1, bytes, archived_at, mime)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(bookmark_id) DO UPDATE SET
                 path=excluded.path, sha1=excluded.sha1, bytes=excluded.bytes,
                 archived_at=excluded.archived_at, mime=excluded.mime""",
            (bookmark_id, path, sha1, nbytes, archived_at, mime))
        self.conn.commit()
        return int(self.conn.execute(
            "SELECT id FROM archives WHERE bookmark_id=?", (bookmark_id,)
        ).fetchone()["id"])

    def get_archive(self, bookmark_id: int):
        row = self.conn.execute(
            "SELECT * FROM archives WHERE bookmark_id=?", (bookmark_id,)).fetchone()
        return dict(row) if row else None

    def archive_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM archives").fetchone()[0])

    def all_archives(self) -> list:
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM archives").fetchall()]

    def delete_archive(self, bookmark_id: int) -> None:
        self.conn.execute("DELETE FROM archives WHERE bookmark_id=?", (bookmark_id,))
        self.conn.commit()

    # -- provenance: acquisitions + data packages --------------------------- #
    def add_acquisition(self, bookmark_id: int, method: str, source=None,
                        acquired_at=None, package_id=None, detail=None,
                        commit: bool = True) -> int:
        import time as _t
        cur = self.conn.execute(
            """INSERT INTO acquisitions
               (bookmark_id, method, source, acquired_at, package_id, detail)
               VALUES (?,?,?,?,?,?)""",
            (bookmark_id, method, source, acquired_at or int(_t.time()),
             package_id, detail))
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

    def acquisition_exists(self, bookmark_id: int, method: str, source,
                           package_id) -> bool:
        row = self.conn.execute(
            """SELECT 1 FROM acquisitions WHERE bookmark_id=? AND method=?
               AND IFNULL(source,'')=IFNULL(?,'')
               AND IFNULL(package_id,0)=IFNULL(?,0) LIMIT 1""",
            (bookmark_id, method, source, package_id)).fetchone()
        return row is not None

    def acquisitions_for(self, bookmark_id: int) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM acquisitions WHERE bookmark_id=? ORDER BY acquired_at",
            (bookmark_id,)).fetchall()]

    def bookmarks_by_acquisition(self, *, method=None, source=None,
                                 package_id=None, limit: int = 500) -> list:
        where, params = [], []
        if method:
            where.append("a.method=?"); params.append(method)
        if source:
            where.append("a.source=?"); params.append(source)
        if package_id:
            where.append("a.package_id=?"); params.append(package_id)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        rows = self.conn.execute(
            f"""SELECT DISTINCT b.* FROM bookmarks b
                JOIN acquisitions a ON a.bookmark_id=b.id{clause}
                ORDER BY b.date_added DESC LIMIT ?""", params).fetchall()
        return self._rows_to_bookmarks(rows)

    def add_package(self, provider: str, source_filename=None, archive_hash=None,
                    export_created_at=None, parser_version=None,
                    retained_path=None, entity_count: int = 0) -> int:
        import time as _t
        self.conn.execute(
            """INSERT OR IGNORE INTO data_packages
               (provider, source_filename, archive_hash, export_created_at,
                imported_at, parser_version, retained_path, entity_count)
               VALUES (?,?,?,?,?,?,?,?)""",
            (provider, source_filename, archive_hash, export_created_at,
             int(_t.time()), parser_version, retained_path, entity_count))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM data_packages WHERE archive_hash=?"
            if archive_hash else "SELECT id FROM data_packages ORDER BY id DESC LIMIT 1",
            (archive_hash,) if archive_hash else ()).fetchone()
        return int(row["id"])

    def package_by_hash(self, archive_hash: str):
        row = self.conn.execute(
            "SELECT * FROM data_packages WHERE archive_hash=?",
            (archive_hash,)).fetchone()
        return dict(row) if row else None

    def update_package_count(self, package_id: int, entity_count: int) -> None:
        self.conn.execute("UPDATE data_packages SET entity_count=? WHERE id=?",
                          (entity_count, package_id))
        self.conn.commit()

    def all_packages(self) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM data_packages ORDER BY imported_at DESC").fetchall()]

    # -- resource kind + relationships -------------------------------------- #
    # -- library facets (filters) ------------------------------------------- #
    def kind_counts(self) -> list:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT kind, COUNT(*) FROM bookmarks GROUP BY kind "
            "ORDER BY COUNT(*) DESC").fetchall()]

    def source_counts(self) -> list:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT source, COUNT(DISTINCT bookmark_id) FROM acquisitions "
            "WHERE source IS NOT NULL AND source <> '' "
            "GROUP BY source ORDER BY COUNT(DISTINCT bookmark_id) DESC").fetchall()]

    def favorite_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM bookmarks WHERE is_favorite=1").fetchone()[0]

    def favorites(self, limit: int = 1000) -> list:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE is_favorite=1 "
            "ORDER BY date_added DESC LIMIT ?", (limit,)).fetchall()
        return self._rows_to_bookmarks(rows)

    def set_kind(self, bookmark_id: int, kind: str) -> None:
        self.conn.execute("UPDATE bookmarks SET kind=? WHERE id=?",
                          (kind, bookmark_id))
        self.conn.commit()

    # -- takeaways: authored distillations ---------------------------------- #
    def add_takeaway(self, bookmark_id: int, text: str, created_at=None) -> int:
        import time as _t
        cur = self.conn.execute(
            "INSERT INTO takeaways(bookmark_id, text, created_at) VALUES (?,?,?)",
            (bookmark_id, text, created_at or int(_t.time())))
        self.conn.commit()
        return int(cur.lastrowid)

    def takeaways_for(self, bookmark_id: int) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM takeaways WHERE bookmark_id=? ORDER BY created_at",
            (bookmark_id,)).fetchall()]

    def all_takeaways(self) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM takeaways ORDER BY created_at DESC").fetchall()]

    def update_takeaway(self, takeaway_id: int, text: str) -> None:
        self.conn.execute("UPDATE takeaways SET text=? WHERE id=?",
                          (text, takeaway_id))
        self.conn.commit()

    def delete_takeaway(self, takeaway_id: int) -> None:
        self.conn.execute("DELETE FROM takeaways WHERE id=?", (takeaway_id,))
        self.conn.commit()

    def reassign_takeaways(self, from_id: int, to_id: int) -> None:
        self.conn.execute(
            "UPDATE takeaways SET bookmark_id=? WHERE bookmark_id=?",
            (to_id, from_id))
        self.conn.commit()

    def enrich_metadata(self, bookmark_id: int, meta: dict) -> None:
        """Fill byline/site_name/published_ts/excerpt from extracted page
        metadata, but only where the resource doesn't already have a value
        (never overwrite better data)."""
        if not meta:
            return
        row = self.conn.execute(
            "SELECT byline, site_name, published_ts, excerpt FROM bookmarks "
            "WHERE id=?", (bookmark_id,)).fetchone()
        if row is None:
            return
        sets, params = [], []
        if not row["byline"] and meta.get("author"):
            sets.append("byline=?"); params.append(meta["author"])
        if not row["site_name"] and meta.get("site_name"):
            sets.append("site_name=?"); params.append(meta["site_name"])
        if not row["published_ts"] and meta.get("published_ts"):
            sets.append("published_ts=?"); params.append(meta["published_ts"])
        if not row["excerpt"] and meta.get("description"):
            sets.append("excerpt=?"); params.append(meta["description"][:280])
        if sets:
            params.append(bookmark_id)
            self.conn.execute(
                f"UPDATE bookmarks SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()

    def bookmarks_by_kind(self, kind: str, limit: int = 500) -> list:
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE kind=? ORDER BY date_added DESC LIMIT ?",
            (kind, limit)).fetchall()
        return self._rows_to_bookmarks(rows)

    def add_relationship(self, src_id: int, dst_id: int, rel: str,
                         detail=None) -> None:
        import json as _json
        d = _json.dumps(detail, ensure_ascii=False) if detail else None
        self.conn.execute(
            "INSERT OR IGNORE INTO relationships(src_id, dst_id, rel, detail) "
            "VALUES (?,?,?,?)", (src_id, dst_id, rel, d))
        if d:   # keep the latest detail (e.g. a start time) if the link existed
            self.conn.execute(
                "UPDATE relationships SET detail=? WHERE src_id=? AND dst_id=? "
                "AND rel=? AND detail IS NULL", (d, src_id, dst_id, rel))
        self.conn.commit()

    def relationship_details_in(self, dst_id: int) -> list:
        """[(rel, source bookmark, detail dict)] for links pointing at dst_id."""
        import json as _json
        rows = self.conn.execute(
            "SELECT b.*, r.rel AS _rel, r.detail AS _detail FROM relationships r "
            "JOIN bookmarks b ON b.id=r.src_id WHERE r.dst_id=?", (dst_id,)).fetchall()
        out = []
        for r in rows:
            try:
                d = _json.loads(r["_detail"]) if r["_detail"] else {}
            except ValueError:
                d = {}
            out.append((r["_rel"], self._row_to_bookmark(r), d))
        return out

    def remove_relationship(self, src_id: int, dst_id: int, rel: str) -> None:
        self.conn.execute(
            "DELETE FROM relationships WHERE src_id=? AND dst_id=? AND rel=?",
            (src_id, dst_id, rel))
        self.conn.commit()

    def relationships_out(self, src_id: int, rel=None) -> list:
        sql = ("SELECT b.*, r.rel AS _rel FROM relationships r "
               "JOIN bookmarks b ON b.id=r.dst_id WHERE r.src_id=?")
        params = [src_id]
        if rel:
            sql += " AND r.rel=?"; params.append(rel)
        rows = self.conn.execute(sql, params).fetchall()
        return [(r["_rel"], self._row_to_bookmark(r)) for r in rows]

    def relationships_in(self, dst_id: int, rel=None) -> list:
        sql = ("SELECT b.*, r.rel AS _rel FROM relationships r "
               "JOIN bookmarks b ON b.id=r.src_id WHERE r.dst_id=?")
        params = [dst_id]
        if rel:
            sql += " AND r.rel=?"; params.append(rel)
        rows = self.conn.execute(sql, params).fetchall()
        return [(r["_rel"], self._row_to_bookmark(r)) for r in rows]

    def year_counts(self) -> List[tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT year, COUNT(*) c FROM bookmarks GROUP BY year ORDER BY year DESC"
        ).fetchall()
        return [(int(r["year"]), int(r["c"])) for r in rows]

    def browser_counts(self) -> List[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT browser, COUNT(*) c FROM bookmarks GROUP BY browser ORDER BY c DESC"
        ).fetchall()
        return [(r["browser"], int(r["c"])) for r in rows]

    def get(self, bookmark_id: int) -> Optional[Bookmark]:
        row = self.conn.execute(
            "SELECT * FROM bookmarks WHERE id=?", (bookmark_id,)
        ).fetchone()
        return self._row_to_bookmark(row) if row else None

    def all_bookmarks(self, limit: int = 0) -> List[Bookmark]:
        sql = "SELECT * FROM bookmarks ORDER BY date_added DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._rows_to_bookmarks(self.conn.execute(sql).fetchall())

    def by_tag(self, tag: str, limit: int = 200) -> List[Bookmark]:
        rows = self.conn.execute(
            """SELECT b.* FROM bookmarks b
               JOIN bookmark_tags bt ON bt.bookmark_id = b.id
               JOIN tags t ON t.id = bt.tag_id
               WHERE t.name = ?
               ORDER BY b.date_added DESC LIMIT ?""",
            (tag, limit)).fetchall()
        return self._rows_to_bookmarks(rows)

    def update_notes(self, bookmark_id: int, notes: str) -> None:
        self.conn.execute("UPDATE bookmarks SET notes=? WHERE id=?",
                          (notes, bookmark_id))
        self.conn.commit()

    def reassign_snippets(self, from_id: int, to_id: int) -> None:
        self.conn.execute("UPDATE snippets SET bookmark_id=? WHERE bookmark_id=?",
                          (to_id, from_id))
        self.conn.commit()

    def delete_bookmark(self, bookmark_id: int) -> None:
        self.conn.execute("DELETE FROM bookmarks WHERE id=?", (bookmark_id,))
        self.conn.commit()

    def get_by_url(self, url: str) -> Optional[Bookmark]:
        row = self.conn.execute(
            "SELECT * FROM bookmarks WHERE url=? ORDER BY id LIMIT 1", (url,)
        ).fetchone()
        return self._row_to_bookmark(row) if row else None

    def find_by_url_pattern(self, pattern: str, limit: int = 500) -> List[Bookmark]:
        """LIKE match on url (use % wildcards). For link-provider queries."""
        rows = self.conn.execute(
            "SELECT * FROM bookmarks WHERE url LIKE ? ORDER BY date_added DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
        return self._rows_to_bookmarks(rows)

    def update_content(self, bookmark_id: int, extracted, fetched_at: int) -> None:
        """Persist extracted page content + metadata. Updating page_text fires
        the FTS AFTER UPDATE trigger, so search picks up page body automatically.
        """
        self.conn.execute(
            """UPDATE bookmarks SET
                 page_text=?, page_title=?, byline=?, site_name=?,
                 published_ts=?, excerpt=?, fetched_at=?
               WHERE id=?""",
            (
                extracted.text or None, extracted.title, extracted.byline,
                extracted.site_name, extracted.published_ts, extracted.excerpt,
                fetched_at, bookmark_id,
            ),
        )
        self.conn.commit()

    def set_favorite(self, bookmark_id: int, value: bool) -> None:
        self.conn.execute(
            "UPDATE bookmarks SET is_favorite=? WHERE id=?",
            (int(value), bookmark_id),
        )
        self.conn.commit()

    # -- feeds -------------------------------------------------------------- #
    def add_feed(self, url: str, title: str = "", site_url: str = None) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO feeds(url, title, site_url) VALUES (?,?,?)",
            (url, title, site_url),
        )
        row = self.conn.execute("SELECT id FROM feeds WHERE url=?", (url,)).fetchone()
        if title:  # keep title fresh on re-subscribe
            self.conn.execute("UPDATE feeds SET title=? WHERE url=?", (title, url))
        self.conn.commit()
        return int(row["id"])

    def list_feeds(self) -> list:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM feeds ORDER BY title, url").fetchall()]

    def touch_feed(self, feed_id: int, ts: int) -> None:
        self.conn.execute(
            "UPDATE feeds SET last_fetched=? WHERE id=?", (ts, feed_id))
        self.conn.commit()

    def remove_feed(self, feed_id: int) -> None:
        self.conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
        self.conn.commit()

    # -- snippets (captured quotations) ------------------------------------- #
    def add_snippet(self, snip) -> int:
        cur = self.conn.execute(
            "INSERT INTO snippets(bookmark_id, quote, note, locator) VALUES (?,?,?,?)",
            (snip.bookmark_id, snip.quote, snip.note, snip.locator),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _row_to_snippet(self, row):
        from .models import Snippet
        return Snippet(
            id=row["id"], bookmark_id=row["bookmark_id"], quote=row["quote"],
            note=row["note"], locator=row["locator"], created_at=row["created_at"],
        )

    def snippets_for(self, bookmark_id: int) -> list:
        rows = self.conn.execute(
            "SELECT * FROM snippets WHERE bookmark_id=? ORDER BY id", (bookmark_id,)
        ).fetchall()
        return [self._row_to_snippet(r) for r in rows]

    def all_snippets(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM snippets ORDER BY created_at DESC").fetchall()
        return [self._row_to_snippet(r) for r in rows]

    def get_snippet(self, snippet_id: int):
        row = self.conn.execute(
            "SELECT * FROM snippets WHERE id=?", (snippet_id,)).fetchone()
        return self._row_to_snippet(row) if row else None

    def delete_snippet(self, snippet_id: int) -> None:
        self.conn.execute("DELETE FROM snippets WHERE id=?", (snippet_id,))
        self.conn.commit()
