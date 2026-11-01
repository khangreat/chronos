"""Firefox-family importers: read moz_bookmarks/moz_places from places.sqlite.

We copy the DB read-only first (Firefox locks it while running), then walk
type=1 rows (bookmarks), resolving folder names via the parent chain.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..core.models import Bookmark
from .base import BrowserImporter, firefox_micros_to_unix, register


def _firefox_profile_roots() -> List[Path]:
    home = Path.home()
    if sys.platform.startswith("win"):
        return [home / "AppData/Roaming/Mozilla/Firefox/Profiles"]
    if sys.platform == "darwin":
        return [home / "Library/Application Support/Firefox/Profiles"]
    return [home / ".mozilla/firefox"]


def _find_places(roots: List[Path]) -> Optional[Path]:
    for root in roots:
        if not root.exists():
            continue
        candidates = sorted(root.glob("*/places.sqlite"))
        # Prefer the default-release profile if present.
        for c in candidates:
            if "default" in c.parent.name:
                return c
        if candidates:
            return candidates[0]
    return None


@register
class FirefoxImporter(BrowserImporter):
    name = "Firefox"

    def default_paths(self) -> List[Path]:
        p = _find_places(_firefox_profile_roots())
        return [p] if p else []

    def parse(self, source: Path) -> List[Bookmark]:
        work = self._readonly_copy(Path(source))
        conn = sqlite3.connect(str(work))
        conn.row_factory = sqlite3.Row
        try:
            return self._extract(conn)
        finally:
            conn.close()

    def _extract(self, conn: sqlite3.Connection) -> List[Bookmark]:
        # Build folder-title map for parent resolution (type=2 are folders).
        folders: Dict[int, str] = {
            r["id"]: (r["title"] or "")
            for r in conn.execute(
                "SELECT id, title FROM moz_bookmarks WHERE type=2"
            )
        }
        rows = conn.execute(
            """
            SELECT b.title AS title, p.url AS url, b.dateAdded AS date_added,
                   b.parent AS parent
            FROM moz_bookmarks b
            JOIN moz_places p ON p.id = b.fk
            WHERE b.type = 1 AND p.url IS NOT NULL
            """
        ).fetchall()

        out: List[Bookmark] = []
        for r in rows:
            url = r["url"]
            if not url or url.startswith(("place:", "javascript:")):
                continue
            out.append(
                Bookmark(
                    url=url,
                    title=(r["title"] or url),
                    date_added=firefox_micros_to_unix(r["date_added"]),
                    browser=self.name,
                    folder_name=folders.get(r["parent"]) or None,
                )
            )
        return out


@register
class MullvadImporter(FirefoxImporter):
    name = "Mullvad"

    def default_paths(self) -> List[Path]:
        home = Path.home()
        roots = [home / ".mullvad/mullvadbrowser/Browser/profile.default"]
        p = _find_places(roots) or _find_places([home / ".mullvad"])
        return [p] if p else []


@register
class TorImporter(FirefoxImporter):
    name = "Tor"

    def default_paths(self) -> List[Path]:
        home = Path.home()
        roots = [
            home / ".tor-browser/app/Browser/TorBrowser/Data/Browser",
            home / "Library/Application Support/TorBrowser-Data/Browser",
        ]
        p = _find_places(roots)
        return [p] if p else []
