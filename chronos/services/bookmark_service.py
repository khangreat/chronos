"""BookmarkService — the coordinated-write seam over Storage.

Import flows go through here: run an importer, then persist. Keeps importers
ignorant of the DB and keeps the GUI/CLI ignorant of storage internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..core.models import Bookmark
from ..core.storage import Storage
from ..importers import all_importers, get_importer
from ..importers.html_import import HTMLImporter


@dataclass
class ImportResult:
    browser: str
    found: int
    inserted: int


class BookmarkService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def import_from(self, browser: str, source: Optional[Path] = None) -> ImportResult:
        importer = get_importer(browser)
        if importer is None:
            raise ValueError(f"Unknown browser/importer: {browser!r}")
        src = Path(source) if source else importer.find_source()
        if src is None or not src.exists():
            raise FileNotFoundError(
                f"No source found for {browser}. Pass an explicit path."
            )
        found = importer.parse(src)
        inserted = self.storage.import_bookmarks(found)
        method = ("browser_history" if "history" in importer.name.lower()
                  else "browser_bookmark")
        self._record_acquisitions(found, method, importer.name.lower().split()[0])
        return ImportResult(importer.name, len(found), inserted)

    def import_html(self, path: Path) -> ImportResult:
        found = HTMLImporter().parse(Path(path))
        inserted = self.storage.import_bookmarks(found)
        self._record_acquisitions(found, "imported", "html")
        return ImportResult("HTML", len(found), inserted)

    def _record_acquisitions(self, found, method: str, source: str) -> None:
        """Give each imported resource an acquisition record (idempotent)."""
        for b in found:
            row = self.storage.get_by_url(b.url)
            if row is None:
                continue
            if not self.storage.acquisition_exists(row.id, method, source, None):
                self.storage.add_acquisition(row.id, method, source,
                                             acquired_at=b.date_added)

    def import_all_available(self) -> List[ImportResult]:
        """Try every registered importer that can auto-locate a source."""
        results: List[ImportResult] = []
        for importer in all_importers():
            src = importer.find_source()
            if src is None:
                continue
            try:
                found = importer.parse(src)
            except Exception:
                # One broken profile must not abort the whole sweep.
                continue
            inserted = self.storage.import_bookmarks(found)
            results.append(ImportResult(importer.name, len(found), inserted))
        return results

    def by_year(self, year: int) -> List[Bookmark]:
        return self.storage.by_year(year)

    def count(self) -> int:
        return self.storage.count()
