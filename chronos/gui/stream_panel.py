"""Center panel: date-grouped bookmark stream, backed by model/view/delegate.

Same public surface as before (set_bookmarks, bookmark_selected, open_requested)
but the view paints only visible rows instead of building a QWidget per row, so
it stays responsive at tens of thousands of items.
"""

from __future__ import annotations

from typing import Dict, List

from .i18n import tr
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListView, QStackedLayout, QVBoxLayout, QWidget,
)

from ..core.models import Bookmark
from .stream_model import BookmarkListModel
from .stream_delegate import BookmarkDelegate


class StreamPanel(QWidget):
    bookmark_selected = Signal(int)
    open_requested = Signal(str)
    selection_changed = Signal(int)          # how many items are selected
    action_requested = Signal(str)           # selection action name
    context_requested = Signal(object)       # global QPoint for a menu

    def __init__(self, tokens: Dict[str, str], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QWidget(); head.setObjectName("PaneHead")
        hl = QHBoxLayout(head); hl.setContentsMargins(4, 0, 4, 0)
        self.heading = QLabel(tr("section.stream"))
        self._is_default_heading = True
        self.heading.setObjectName("PaneTitle")
        self.count_label = QLabel("")
        self.count_label.setObjectName("PaneCount")
        hl.addWidget(self.heading, 1)
        hl.addWidget(self.count_label)
        lay.addWidget(head)

        self.model = BookmarkListModel()
        self.view = QListView()
        self.view.setObjectName("Stream")
        self.view.setModel(self.model)
        self.view.setItemDelegate(BookmarkDelegate(tokens))
        # Ctrl/Shift-click and Ctrl+A select several items for AI and bulk actions
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.view.viewport().mapToGlobal(pos)))
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setUniformItemSizes(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMouseTracking(True)
        self.view.setAccessibleName("Items")
        self.view.setAccessibleDescription(
            "Your archive for the chosen period, search or filter. Arrow keys open "
            "items in the reader; Enter or double-click opens the original.")
        self.view.clicked.connect(self._on_click)
        self.view.doubleClicked.connect(self._on_double)
        # keyboard browsing: moving the selection opens the item in the reader
        self._just_emitted = None
        from PySide6.QtGui import QKeySequence, QShortcut
        for keys in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(keys), self.view)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(lambda: self._on_double(self.view.currentIndex())
                                 if self.view.currentIndex().isValid() else None)
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.view.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection())

        # selection bar — appears when two or more items are selected
        self.selbar = QWidget(); self.selbar.setObjectName("SelBar")
        sl = QHBoxLayout(self.selbar); sl.setContentsMargins(8, 6, 6, 6); sl.setSpacing(6)
        self.sel_label = QLabel(""); self.sel_label.setObjectName("SelCount")
        sl.addWidget(self.sel_label, 1)
        from PySide6.QtWidgets import QMenu, QPushButton, QToolButton
        self.ask_btn = QPushButton("Ask AI\u2026"); self.ask_btn.setObjectName("PrimaryButton")
        self.ask_btn.setToolTip("Ask an AI about the selected items (Ctrl+Shift+A)")
        self.ask_btn.clicked.connect(lambda: self.action_requested.emit("ask_ai"))
        self.copy_btn = QPushButton("Copy for AI")
        self.copy_btn.setToolTip("Copy the selected items, with your quotes and "
                                 "takeaways, to paste into any AI chat")
        self.copy_btn.clicked.connect(lambda: self.action_requested.emit("copy_ai"))
        self.sel_more = QToolButton(); self.sel_more.setObjectName("MoreButton")
        self.sel_more.setText("\u22ef"); self.sel_more.setAccessibleName("More for the selection")
        self.sel_more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.sel_more)
        for label, name in (("Save for AI\u2026", "save_ai"), ("Add to favourites", "favorite"),
                            ("Add a tag\u2026", "tag"), ("Export these\u2026", "export"),
                            ("Remove from archive\u2026", "remove"),
                            ("Clear selection", "clear")):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, n=name: self.action_requested.emit(n))
        self.sel_more.setMenu(m)
        for w in (self.ask_btn, self.copy_btn, self.sel_more):
            sl.addWidget(w)
        self.selbar.setVisible(False)

        self.empty = QLabel("")
        self.empty.setObjectName("ReaderMeta")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.empty.setContentsMargins(8, 12, 8, 0)
        stack_host = QWidget()
        self._stack = QStackedLayout(stack_host)
        self._stack.addWidget(self.view)
        self._stack.addWidget(self.empty)
        lay.addWidget(stack_host, 1)
        lay.addWidget(self.selbar)

    # -- selection ---------------------------------------------------------- #
    def selected_ids(self):
        """Selected items in list order (falls back to the current item)."""
        rows = sorted({i.row() for i in self.view.selectionModel().selectedIndexes()})
        if not rows and self.view.currentIndex().isValid():
            rows = [self.view.currentIndex().row()]
        out = []
        for r in rows:
            b = self.model.bookmark_at(r)
            if b is not None and b.id is not None:
                out.append(int(b.id))
        return out

    def selected_count(self) -> int:
        return len({i.row() for i in self.view.selectionModel().selectedIndexes()})

    def _on_selection(self) -> None:
        n = self.selected_count()
        self.sel_label.setText(f"{n} selected")
        self.selbar.setVisible(n >= 2)
        self.selection_changed.emit(n)

    def clear_selection(self) -> None:
        self.view.clearSelection()

    def _set_head(self, heading: str, count) -> None:
        self.heading.setText(heading)
        self.view.itemDelegate().suppress_header = heading
        self._is_default_heading = False
        self.count_label.setText(f"{count:,}" if count else "")

    def set_bookmarks(self, bookmarks: List[Bookmark], heading: str,
                      count=None, empty_hint: str = "") -> None:
        self._set_head(heading, len(bookmarks) if count is None else count)
        self.model.set_bookmarks(bookmarks)
        self._show_empty(not bookmarks, empty_hint)

    def set_period(self, storage, year: int, month: int, heading: str,
                   count=None) -> None:
        self._set_head(heading, count)
        self.model.set_period(storage, year, month)
        self._show_empty(False, "")

    def _show_empty(self, empty: bool, hint: str) -> None:
        self.empty.setText(hint or "Nothing here.")
        self._stack.setCurrentIndex(1 if empty else 0)

    def count(self) -> int:
        return self.model.item_count()

    def set_tokens(self, tokens: Dict[str, str]) -> None:
        self.view.itemDelegate().t = tokens
        self.view.doItemsLayout()          # row heights depend on text size
        self.view.viewport().update()

    def _on_current(self, index, _prev=None) -> None:
        if not index.isValid():
            return
        b = self.model.bookmark_at(index.row())
        if b is not None and b.id is not None:
            self._just_emitted = int(b.id)
            self.bookmark_selected.emit(int(b.id))

    def _on_click(self, index) -> None:
        b = self.model.bookmark_at(index.row())
        if b is None or b.id is None:
            return
        if self._just_emitted == int(b.id):   # the press already opened it
            self._just_emitted = None
        from PySide6.QtGui import QKeySequence, QShortcut
        for keys in ("Return", "Enter"):
            sc = QShortcut(QKeySequence(keys), self.view)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(lambda: self._on_double(self.view.currentIndex())
                                 if self.view.currentIndex().isValid() else None)
            return
        self.bookmark_selected.emit(int(b.id))

    def _on_double(self, index) -> None:
        b = self.model.bookmark_at(index.row())
        if b is not None:
            self.open_requested.emit(b.url)

    def retranslate(self) -> None:
        if getattr(self, "_is_default_heading", True):
            self.heading.setText(tr("section.stream"))
