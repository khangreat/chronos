"""Schema versioning + forward-migration registry.

The DB carries its own version in `schema_version`. On open, Storage applies
every migration whose target version is greater than the stored version, in
order. Adding a schema change = appending one migration function; never edit an
already-shipped migration.

Design choices:
  - Normalised tags: bookmarks / tags / bookmark_tags (no comma-joined TEXT).
  - FTS5 virtual table mirrors bookmarks(title, url, page_text), kept current by
    triggers so search is done by SQLite, not a Python loop.
"""

from __future__ import annotations

import sqlite3
from typing import Callable, List

# Each entry: (target_version, migrate_fn). Append only.
MIGRATIONS: List[tuple[int, Callable[[sqlite3.Connection], None]]] = []


def migration(version: int):
    def deco(fn: Callable[[sqlite3.Connection], None]):
        MIGRATIONS.append((version, fn))
        return fn
    return deco


def current_target_version() -> int:
    return max((v for v, _ in MIGRATIONS), default=0)


def get_db_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        return 0
    return int(row[0])


def set_db_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring the connection's DB up to the latest schema. Returns final version."""
    version = get_db_version(conn)
    for target, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
        if target > version:
            fn(conn)
            set_db_version(conn, target)
            version = target
    conn.commit()
    return version


# --------------------------------------------------------------------------- #
# v1 — initial normalised schema + FTS5
# --------------------------------------------------------------------------- #
@migration(1)
def _v1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE bookmarks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            browser      TEXT    NOT NULL DEFAULT 'Firefox',
            title        TEXT    NOT NULL DEFAULT '',
            url          TEXT    NOT NULL,
            date_added   INTEGER NOT NULL,          -- UNIX seconds (UTC)
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            folder_name  TEXT,
            page_text    TEXT,
            is_favorite  INTEGER NOT NULL DEFAULT 0,
            notes        TEXT    NOT NULL DEFAULT '',
            is_dead      INTEGER NOT NULL DEFAULT 0,
            wayback_url  TEXT,
            last_checked INTEGER,
            created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            UNIQUE(browser, url)
        );

        CREATE INDEX idx_bm_year_month ON bookmarks(year, month);
        CREATE INDEX idx_bm_browser    ON bookmarks(browser);
        CREATE INDEX idx_bm_favorite   ON bookmarks(is_favorite);

        CREATE TABLE tags (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE bookmark_tags (
            bookmark_id INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            tag_id      INTEGER NOT NULL REFERENCES tags(id)      ON DELETE CASCADE,
            PRIMARY KEY (bookmark_id, tag_id)
        );

        CREATE VIRTUAL TABLE bookmarks_fts USING fts5(
            title, url, page_text,
            content='bookmarks',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );

        -- Keep FTS in lockstep with the base table.
        CREATE TRIGGER bm_ai AFTER INSERT ON bookmarks BEGIN
            INSERT INTO bookmarks_fts(rowid, title, url, page_text)
            VALUES (new.id, new.title, new.url, coalesce(new.page_text,''));
        END;
        CREATE TRIGGER bm_ad AFTER DELETE ON bookmarks BEGIN
            INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, page_text)
            VALUES ('delete', old.id, old.title, old.url, coalesce(old.page_text,''));
        END;
        CREATE TRIGGER bm_au AFTER UPDATE ON bookmarks BEGIN
            INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, page_text)
            VALUES ('delete', old.id, old.title, old.url, coalesce(old.page_text,''));
            INSERT INTO bookmarks_fts(rowid, title, url, page_text)
            VALUES (new.id, new.title, new.url, coalesce(new.page_text,''));
        END;
        """
    )


# --------------------------------------------------------------------------- #
# v2 — extracted-page / citation metadata (for reader view + cross-app citing)
# --------------------------------------------------------------------------- #
@migration(2)
def _v2(conn: sqlite3.Connection) -> None:
    # SQLite ALTER TABLE ADD COLUMN is safe and cheap; proves forward migration
    # across a real version bump. FTS wiring (page_text) is untouched.
    for col, decl in [
        ("page_title", "TEXT"),
        ("byline", "TEXT"),
        ("site_name", "TEXT"),
        ("published_ts", "INTEGER"),
        ("excerpt", "TEXT"),
        ("fetched_at", "INTEGER"),
    ]:
        conn.execute(f"ALTER TABLE bookmarks ADD COLUMN {col} {decl}")


# --------------------------------------------------------------------------- #
# v3 — RSS/Atom feed subscriptions
# --------------------------------------------------------------------------- #
@migration(3)
def _v3(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE feeds (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            url          TEXT NOT NULL UNIQUE,   -- the feed URL
            title        TEXT NOT NULL DEFAULT '',
            site_url     TEXT,                   -- the site the feed belongs to
            last_fetched INTEGER,
            added_at     INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX idx_feeds_url ON feeds(url);
        """
    )


# --------------------------------------------------------------------------- #
# v4 — captured quotations (snippets) for citing into Nawishtar
# --------------------------------------------------------------------------- #
@migration(4)
def _v4(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE snippets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            quote       TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT '',
            locator     TEXT,
            created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX idx_snippets_bm ON snippets(bookmark_id);
        """
    )


# --------------------------------------------------------------------------- #
# v5 — offline full-page archives (one snapshot per bookmark)
# --------------------------------------------------------------------------- #
@migration(5)
def _v5(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE archives (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id INTEGER NOT NULL UNIQUE
                        REFERENCES bookmarks(id) ON DELETE CASCADE,
            path        TEXT NOT NULL,     -- gzipped raw HTML on disk
            sha1        TEXT NOT NULL,
            bytes       INTEGER NOT NULL,  -- uncompressed size
            archived_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        """
    )


# --------------------------------------------------------------------------- #
# v6 — provenance: how a resource entered, and account-export data packages
# --------------------------------------------------------------------------- #
@migration(6)
def _v6(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE data_packages (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            provider          TEXT NOT NULL,     -- reddit, google_takeout, facebook, x…
            source_filename   TEXT,
            archive_hash      TEXT UNIQUE,       -- sha256 of the original package
            export_created_at INTEGER,
            imported_at       INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            parser_version    TEXT,
            retained_path     TEXT,              -- where the original file is kept
            entity_count      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE acquisitions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            method      TEXT NOT NULL,   -- browser_bookmark, browser_history,
                                         -- feed_discovered, manual_capture,
                                         -- platform_saved, platform_liked,
                                         -- imported, received_from_bridge
            source      TEXT,            -- reddit, firefox, rss, <feed title>…
            acquired_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            package_id  INTEGER REFERENCES data_packages(id) ON DELETE SET NULL,
            detail      TEXT             -- optional JSON (permalink, parent_id…)
        );
        CREATE INDEX idx_acq_bm ON acquisitions(bookmark_id);
        CREATE INDEX idx_acq_method ON acquisitions(method);
        CREATE INDEX idx_acq_source ON acquisitions(source);

        -- Backfill: every existing resource gets provenance inferred from its
        -- browser field, so nothing lacks an acquisition record.
        INSERT INTO acquisitions(bookmark_id, method, source, acquired_at)
        SELECT id,
          CASE WHEN browser='RSS' THEN 'feed_discovered'
               WHEN browser IN ('Firefox','Chrome','Edge','Brave','Vivaldi',
                                'Opera','Mullvad','Tor') THEN 'browser_bookmark'
               ELSE 'imported' END,
          lower(browser),
          date_added
        FROM bookmarks;
        """
    )


# --------------------------------------------------------------------------- #
# v7 — resource kind + relationships (evolution toward the Resource model)
# --------------------------------------------------------------------------- #
@migration(7)
def _v7(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        ALTER TABLE bookmarks ADD COLUMN kind TEXT NOT NULL DEFAULT 'webpage';

        CREATE TABLE relationships (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            src_id     INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            dst_id     INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            rel        TEXT NOT NULL,   -- reply_to, quotes, in_thread, related, links_to
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            UNIQUE(src_id, dst_id, rel)
        );
        CREATE INDEX idx_rel_src ON relationships(src_id);
        CREATE INDEX idx_rel_dst ON relationships(dst_id);

        -- Backfill kind from browser where we can infer it.
        UPDATE bookmarks SET kind='feed_entry' WHERE browser='RSS';
        """
    )


# --------------------------------------------------------------------------- #
# v8 — takeaways: authored distillations (distinct from quotes and notes)
# --------------------------------------------------------------------------- #
@migration(8)
def _v8(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE takeaways (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id INTEGER NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
            text        TEXT NOT NULL,
            created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX idx_takeaway_bm ON takeaways(bookmark_id);
        """
    )


# --------------------------------------------------------------------------- #
# v9 — videos: relationship detail (e.g. start time), and video kind backfill
# --------------------------------------------------------------------------- #
@migration(9)
def _v9(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        ALTER TABLE relationships ADD COLUMN detail TEXT;
        UPDATE bookmarks SET kind='video'
         WHERE kind IN ('webpage','generic')
           AND (url LIKE '%youtube.com/watch%' OR url LIKE '%youtu.be/%'
                OR url LIKE '%youtube.com/shorts/%' OR url LIKE '%youtube.com/embed/%'
                OR url LIKE '%youtube.com/live/%' OR url LIKE '%vimeo.com/%');
        """
    )


# --------------------------------------------------------------------------- #
# v10 — find items by address quickly. Every import looks items up by URL (and
# by browser + URL); without these, a Takeout's years of history took minutes.
# Indexes only: no data changes.
# --------------------------------------------------------------------------- #
@migration(10)
def _v10(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_bm_url ON bookmarks(url);
        CREATE INDEX IF NOT EXISTS idx_bm_browser_url ON bookmarks(browser, url);
        CREATE INDEX IF NOT EXISTS idx_acq_lookup ON acquisitions(bookmark_id, method);
        """
    )


# --------------------------------------------------------------------------- #
# v11 — sites. Each item's site (domain) is stored and indexed; your own rules
# per site; the outcome of the last fetch or link check per item (so "couldn't
# save: the site refused" is remembered, and runs resume); what kind of file an
# offline copy is (web page, PDF, plain text). Adds columns and tables only.
# --------------------------------------------------------------------------- #
@migration(11)
def _v11(conn: sqlite3.Connection) -> None:
    from ..web.sites import domain_of
    conn.create_function("chronos_domain", 1, lambda u: domain_of(u or ""))
    conn.executescript(
        """
        ALTER TABLE bookmarks ADD COLUMN domain TEXT;
        UPDATE bookmarks SET domain = chronos_domain(url);
        CREATE INDEX IF NOT EXISTS idx_bm_domain ON bookmarks(domain);

        ALTER TABLE archives ADD COLUMN mime TEXT NOT NULL DEFAULT 'text/html';

        CREATE TABLE site_rules (
            domain     TEXT PRIMARY KEY,
            mode       TEXT NOT NULL,          -- fetch | metadata | login | skip
            pace       REAL,                   -- seconds between requests
            extractor  TEXT,                   -- NULL = the Settings choice
            note       TEXT,
            updated_at INTEGER
        );

        CREATE TABLE fetch_log (
            bookmark_id INTEGER PRIMARY KEY REFERENCES bookmarks(id) ON DELETE CASCADE,
            status      TEXT NOT NULL,   -- ok | moved | dead | blocked | login | busy |
                                         -- error | unreachable | timeout | skipped |
                                         -- not_page | private
            code        INTEGER,         -- HTTP status, if any
            reason      TEXT,            -- in plain words
            final_url   TEXT,            -- where the address led (redirects)
            kind        TEXT,            -- copy | check | metadata
            attempted_at INTEGER NOT NULL,
            attempts    INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX idx_fetch_status ON fetch_log(status);
        """
    )
