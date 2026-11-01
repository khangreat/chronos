"""Browser *history* importers (visited pages, not just bookmarks).

Reuses the importer framework. History is deduplicated to one row per URL at
its most recent visit, so a browser that visited a page 40 times yields one
entry timestamped at the last visit. Timestamps use each family's native epoch
(Firefox µs-since-1970, Chromium µs-since-1601), normalised to UNIX seconds.

These get their own `browser` label ("Firefox history", "Chrome history") so
history and bookmarks stay distinguishable and the (browser, url) uniqueness
never collides a bookmark with a history hit.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import List

from ..core.models import Bookmark
from .base import BrowserImporter, firefox_micros_to_unix, register, webkit_micros_to_unix


@register
class FirefoxHistoryImporter(BrowserImporter):
    name = "Firefox history"

    def default_paths(self) -> List[Path]:
        from .firefox import _find_places, _firefox_profile_roots
        p = _find_places(_firefox_profile_roots())
        return [p] if p else []

    def parse(self, source: Path) -> List[Bookmark]:
        work = self._readonly_copy(Path(source))
        conn = sqlite3.connect(str(work))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT p.url AS url, p.title AS title,
                       MAX(v.visit_date) AS last_visit
                FROM moz_places p
                JOIN moz_historyvisits v ON v.place_id = p.id
                WHERE p.url IS NOT NULL
                GROUP BY p.id
                """
            ).fetchall()
        finally:
            conn.close()
        out: List[Bookmark] = []
        for r in rows:
            url = r["url"]
            if not url or url.startswith(("place:", "javascript:")):
                continue
            out.append(Bookmark(
                url=url, title=(r["title"] or url),
                date_added=firefox_micros_to_unix(r["last_visit"]),
                browser=self.name,
            ))
        return out


class ChromiumHistoryImporter(BrowserImporter):
    name = "Chromium history"
    vendor_subdir = ""

    def _config_root(self) -> Path:
        home = Path.home()
        if sys.platform.startswith("win"):
            return home / "AppData/Local"
        if sys.platform == "darwin":
            return home / "Library/Application Support"
        return home / ".config"

    def default_paths(self) -> List[Path]:
        from .profiles import discover
        browser = self.name.replace(" history", "")
        return [p.history for p in discover()
                if p.family == "chromium" and p.browser == browser and p.history]

    def parse(self, source: Path) -> List[Bookmark]:
        work = self._readonly_copy(Path(source))
        conn = sqlite3.connect(str(work))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT url, title, last_visit_time
                   FROM urls WHERE url IS NOT NULL"""
            ).fetchall()
        finally:
            conn.close()
        out: List[Bookmark] = []
        for r in rows:
            url = r["url"]
            if not url or url.startswith("javascript:"):
                continue
            out.append(Bookmark(
                url=url, title=(r["title"] or url),
                date_added=webkit_micros_to_unix(r["last_visit_time"]),
                browser=self.name,
            ))
        return out


@register
class ChromeHistoryImporter(ChromiumHistoryImporter):
    name = "Chrome history"
    vendor_subdir = "Google/Chrome"


@register
class EdgeHistoryImporter(ChromiumHistoryImporter):
    name = "Edge history"
    vendor_subdir = "Microsoft/Edge"


@register
class BraveHistoryImporter(ChromiumHistoryImporter):
    name = "Brave history"
    vendor_subdir = "BraveSoftware/Brave-Browser"
