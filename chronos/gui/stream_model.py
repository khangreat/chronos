"""Stream list model — lazy (keyset) for periods, eager for search.

Period views page in on demand via canFetchMore/fetchMore, so a period with
hundreds of thousands of rows never materialises all at once. Search results
(already bounded) are set eagerly. Header entries mark month boundaries and are
non-selectable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from ..core.models import Bookmark

ENTRY_ROLE = Qt.UserRole + 1

_MONTHS = ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
           "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


@dataclass
class Entry:
    kind: str                    # "header" | "item"
    text: str = ""
    bookmark: Optional[Bookmark] = None


class BookmarkListModel(QAbstractListModel):
    PAGE = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[Entry] = []
        self._storage = None
        self._year = 0
        self._month = 0
        self._last_key = None          # (date_added, id) for keyset
        self._last_group = None
        self._exhausted = True

    # -- eager (search) ----------------------------------------------------- #
    def set_bookmarks(self, bookmarks: List[Bookmark]) -> None:
        self.beginResetModel()
        self._storage = None
        self._exhausted = True
        self._entries = []
        self._last_group = None
        self._append(bookmarks)
        self.endResetModel()

    # -- lazy (period) ------------------------------------------------------ #
    def set_period(self, storage, year: int, month: int) -> None:
        self.beginResetModel()
        self._storage = storage
        self._year, self._month = year, month
        self._entries = []
        self._last_key = None
        self._last_group = None
        self._exhausted = False
        page = storage.page_period(year, month, after=None, limit=self.PAGE)
        self._ingest(page)
        self.endResetModel()

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return not parent.isValid() and not self._exhausted

    def fetchMore(self, parent=QModelIndex()) -> None:
        if parent.isValid() or self._exhausted or self._storage is None:
            return
        page = self._storage.page_period(
            self._year, self._month, after=self._last_key, limit=self.PAGE)
        start = len(self._entries)
        new = self._build_entries(page)
        if not page or len(page) < self.PAGE:
            self._exhausted = True
        if not new:
            return
        self.beginInsertRows(QModelIndex(), start, start + len(new) - 1)
        self._entries.extend(new)
        self.endInsertRows()

    def _ingest(self, page) -> None:
        self._entries.extend(self._build_entries(page))
        if not page or len(page) < self.PAGE:
            self._exhausted = True

    def _build_entries(self, page) -> List[Entry]:
        built: List[Entry] = []
        for b in page:
            group = (b.year, b.month)
            if group != self._last_group:
                built.append(Entry("header", f"{_MONTHS[b.month]} {b.year}"))
                self._last_group = group
            built.append(Entry("item", bookmark=b))
            self._last_key = (b.date_added, b.id)
        return built

    def _append(self, bookmarks) -> None:
        self._entries.extend(self._build_entries(bookmarks))

    # -- read --------------------------------------------------------------- #
    def item_count(self) -> int:
        return sum(1 for e in self._entries if e.kind == "item")

    def bookmark_at(self, row: int) -> Optional[Bookmark]:
        if 0 <= row < len(self._entries):
            return self._entries[row].bookmark
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role == ENTRY_ROLE:
            return entry
        if role == Qt.DisplayRole:
            if entry.kind == "header":
                return entry.text
            b = entry.bookmark
            return (b.title or b.url) if b else ""
        if role == Qt.AccessibleTextRole and entry.kind != "header" and entry.bookmark:
            from .reader_panel import byline_for
            b = entry.bookmark
            bits = [b.title or b.url, byline_for(b)]
            if b.is_favorite:
                bits.append("Favourite")
            if b.is_dead:
                bits.append("Link no longer loads")
            if b.tags:
                bits.append("Tags: " + ", ".join(b.tags[:4]))
            return ". ".join(bits) + "."
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        if self._entries[index.row()].kind == "header":
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
