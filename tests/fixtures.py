"""Build real-format browser fixtures on disk. No mocks of the parse path —
these are the actual schemas/formats each importer meets in the wild.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_WEBKIT_OFFSET = 11_644_473_600


def unix_to_firefox_micros(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) * 1_000_000


def unix_to_webkit_micros(dt: datetime) -> int:
    return (int(dt.replace(tzinfo=timezone.utc).timestamp()) + _WEBKIT_OFFSET) * 1_000_000


def build_firefox_places(path: Path) -> None:
    """Create a places.sqlite with the real moz_places/moz_bookmarks shape."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE moz_places (
            id INTEGER PRIMARY KEY, url TEXT, title TEXT
        );
        CREATE TABLE moz_bookmarks (
            id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER,
            parent INTEGER, title TEXT, dateAdded INTEGER
        );
        """
    )
    # A folder (type=2) and three bookmarks (type=1), plus a place: junk entry.
    conn.execute("INSERT INTO moz_bookmarks VALUES (10,2,NULL,1,'Programming',0)")
    places = [
        (1, "https://docs.python.org", "Python Docs",
         datetime(2024, 1, 15, 14, 30)),
        (2, "https://realpython.com", "Real Python",
         datetime(2023, 12, 10, 9, 15)),
        (3, "https://github.com", "GitHub",
         datetime(2022, 6, 1, 0, 0)),
    ]
    for pid, url, title, dt in places:
        conn.execute("INSERT INTO moz_places VALUES (?,?,?)", (pid, url, title))
        conn.execute(
            "INSERT INTO moz_bookmarks VALUES (?,?,?,?,?,?)",
            (100 + pid, 1, pid, 10, title, unix_to_firefox_micros(dt)),
        )
    # place: URI that must be filtered out.
    conn.execute("INSERT INTO moz_places VALUES (99,'place:type=6','Recent Tags')")
    conn.execute(
        "INSERT INTO moz_bookmarks VALUES (199,1,99,10,'Recent Tags',?)",
        (unix_to_firefox_micros(datetime(2024, 1, 1)),),
    )
    conn.commit()
    conn.close()


def build_chromium_bookmarks(path: Path) -> None:
    """Create a Chromium 'Bookmarks' JSON with WebKit-epoch timestamps."""
    data = {
        "roots": {
            "bookmark_bar": {
                "type": "folder", "name": "Bookmark Bar",
                "children": [
                    {
                        "type": "url", "name": "Rust Book",
                        "url": "https://doc.rust-lang.org/book/",
                        "date_added": str(unix_to_webkit_micros(
                            datetime(2024, 3, 20, 10, 0))),
                    },
                    {
                        "type": "folder", "name": "News",
                        "children": [
                            {
                                "type": "url", "name": "Hacker News",
                                "url": "https://news.ycombinator.com",
                                "date_added": str(unix_to_webkit_micros(
                                    datetime(2023, 8, 5, 8, 0))),
                            }
                        ],
                    },
                ],
            },
            "other": {"type": "folder", "name": "Other", "children": []},
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def build_netscape_html(path: Path) -> None:
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3>Learning</H3>
    <DL><p>
        <DT><A HREF="https://sqlite.org/fts5.html" ADD_DATE="1700000000">SQLite FTS5</A>
        <DT><A HREF="https://qt.io" ADD_DATE="1650000000">Qt</A>
    </DL><p>
    <DT><A HREF="https://example.com" ADD_DATE="1600000000">Example</A>
</DL><p>
"""
    path.write_text(html, encoding="utf-8")


def build_firefox_history(path: Path) -> None:
    """places.sqlite with moz_places + moz_historyvisits (visited pages)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE moz_historyvisits (
            id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER
        );
        """
    )
    pages = [
        (1, "https://news.example.com/a", "Article A", datetime(2024, 2, 1)),
        (2, "https://blog.example.com/b", "Post B", datetime(2023, 11, 5)),
    ]
    for pid, url, title, dt in pages:
        conn.execute("INSERT INTO moz_places VALUES (?,?,?)", (pid, url, title))
        # multiple visits; importer should keep the latest
        conn.execute("INSERT INTO moz_historyvisits(place_id, visit_date) VALUES (?,?)",
                     (pid, unix_to_firefox_micros(dt.replace(day=1))))
        conn.execute("INSERT INTO moz_historyvisits(place_id, visit_date) VALUES (?,?)",
                     (pid, unix_to_firefox_micros(dt)))
    conn.commit()
    conn.close()


def build_chromium_history(path: Path) -> None:
    """Chromium 'History' sqlite with the urls table (WebKit epoch)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT,"
        " last_visit_time INTEGER)"
    )
    rows = [
        ("https://docs.rs/tokio", "tokio docs", datetime(2024, 4, 2)),
        ("https://crates.io", "crates.io", datetime(2023, 9, 9)),
    ]
    for url, title, dt in rows:
        conn.execute(
            "INSERT INTO urls(url, title, last_visit_time) VALUES (?,?,?)",
            (url, title, unix_to_webkit_micros(dt)),
        )
    conn.commit()
    conn.close()
