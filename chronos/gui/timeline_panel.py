"""Left panel: the timeline spine (years -> months) plus browser/tag filters.

Emits `period_selected(year, month)` where month=0 means the whole year, and
`filter_changed()` when a browser/tag filter toggles. Pure view — it reads
aggregates from the context's stats/storage and never writes.
"""

from __future__ import annotations

from typing import Optional

from .i18n import tr
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
_COUNT_COLOR = "#6B7280"

# Roles on tree items
_YEAR = Qt.UserRole + 1
_MONTH = Qt.UserRole + 2


_KIND_PLURAL = {
    "social_post": "Posts", "social_comment": "Comments", "thread": "Threads",
    "article": "Articles", "feed_entry": "Feed items", "webpage": "Pages",
    "image": "Images", "place": "Places", "product": "Products", "generic": "Other",
    "video": "Videos",
}
_FACET = Qt.UserRole + 3
_VALUE = Qt.UserRole + 4


class TimelinePanel(QWidget):
    period_selected = Signal(int, int)  # (year, month) — month 0 = all year
    library_selected = Signal(str, str)  # (facet, value): favorites|kind|source

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        header = QLabel(tr("section.timeline"))
        self._header = header
        header.setObjectName("PaneTitle")
        lay.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setObjectName("Spine")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(12)
        self.tree.setRootIsDecorated(False)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.setAccessibleName("Timeline")
        self.tree.setAccessibleDescription(
            "Years and months in your archive. Choose one to list its items.")
        lay.addWidget(self.tree, 3)

        lib_head = QLabel("Library")
        lib_head.setObjectName("PaneTitle")
        self._lib_head = lib_head
        lay.addWidget(lib_head)
        self.library = QTreeWidget()
        self.library.setObjectName("Spine")
        self.library.setHeaderHidden(True)
        self.library.setColumnCount(2)
        self.library.setIndentation(12)
        self.library.setRootIsDecorated(False)
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lh = self.library.header()
        lh.setStretchLastSection(False)
        lh.setSectionResizeMode(0, QHeaderView.Stretch)
        lh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.library.itemClicked.connect(self._on_library)
        self.library.itemActivated.connect(self._on_library)
        self.tree.itemActivated.connect(self._on_click)
        self.library.setAccessibleName("Library filters")
        self.library.setAccessibleDescription(
            "Favourites, kinds of item, and where items came from.")
        lay.addWidget(self.library, 2)

        self.reload()

    def reload(self) -> None:
        self._reload_library()
        self.tree.clear()
        timeline = self.ctx.stats.timeline()  # {year: [(month, count), ...]}
        for year in sorted(timeline, reverse=True):
            months = timeline[year]
            total = sum(c for _, c in months)
            y_item = QTreeWidgetItem([str(year), f"{total:,}"])
            f = QFont(y_item.font(0)); f.setWeight(QFont.DemiBold)
            y_item.setFont(0, f)
            self._style_count(y_item)
            y_item.setData(0, _YEAR, year)
            y_item.setData(0, _MONTH, 0)
            self.tree.addTopLevelItem(y_item)
            for m, c in sorted(months):
                m_item = QTreeWidgetItem([_MONTHS[m], f"{c:,}"])
                self._style_count(m_item)
                m_item.setData(0, _YEAR, year)
                m_item.setData(0, _MONTH, m)
                y_item.addChild(m_item)
            y_item.setExpanded(True)

    def mark(self, year: int, month: int) -> None:
        """Highlight the period being shown, without emitting a selection."""
        it = self.tree.invisibleRootItem()
        for i in range(it.childCount()):
            y = it.child(i)
            if y.data(0, _YEAR) != year:
                continue
            target = y
            for j in range(y.childCount()):
                if y.child(j).data(0, _MONTH) == month:
                    target = y.child(j)
            self.tree.setCurrentItem(target)
            return

    def _reload_library(self) -> None:
        from .reader_panel import _src
        self.library.clear()
        st = self.ctx.storage

        def add(label, count, facet, value, parent=None, bold=False):
            it = QTreeWidgetItem([label, f"{count:,}" if count else ""])
            it.setData(0, _FACET, facet)
            it.setData(0, _VALUE, value)
            if bold:
                f = QFont(it.font(0)); f.setWeight(QFont.DemiBold); it.setFont(0, f)
            self._style_count(it)
            (parent.addChild(it) if parent else self.library.addTopLevelItem(it))
            return it

        fav = st.favorite_count()
        if fav:
            add("\u2605  Favourites", fav, "favorites", "")
        kinds = st.kind_counts()
        if len(kinds) > 1:
            head = add("Kinds", 0, "", "", bold=True)
            for kind, n in kinds:
                add(_KIND_PLURAL.get(kind, kind), n, "kind", kind, head)
            head.setExpanded(True)
        sources = st.source_counts()
        if sources:
            head = add("Sources", 0, "", "", bold=True)
            for src, n in sources:
                add(_src(src), n, "source", src, head)
            head.setExpanded(True)
        has = self.library.topLevelItemCount() > 0
        self.library.setVisible(has)
        self._lib_head.setVisible(has)

    def _on_library(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        facet = item.data(0, _FACET)
        if not facet:
            item.setExpanded(not item.isExpanded())
            return
        self.tree.clearSelection()
        self.library_selected.emit(str(facet), str(item.data(0, _VALUE) or ""))

    @staticmethod
    def _style_count(item: QTreeWidgetItem) -> None:
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setForeground(1, QBrush(QColor(_COUNT_COLOR)))

    def _on_click(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        self.library.clearSelection()
        self._on_period(item)

    def _on_period(self, item: QTreeWidgetItem) -> None:
        year = item.data(0, _YEAR)
        month = item.data(0, _MONTH) or 0
        if year is not None:
            self.period_selected.emit(int(year), int(month))

    def retranslate(self) -> None:
        self._header.setText(tr("section.timeline"))
