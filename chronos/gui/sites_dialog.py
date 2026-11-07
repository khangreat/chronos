"""The Sites window — every site in your archive, its numbers, and its rule.

Top: the overview (how many sites, how much is kept offline, what's gone) and a
chart of your biggest sites, each bar showing how much of it you have offline.
Middle: a sortable, filterable table. Right: the chosen site — its numbers, its
rule (save pages / titles only / needs login / never fetch, how many seconds
between requests, which text extractor), and what to do with it.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..web.sites import BUILTIN, DEFAULT_PACE, MODE_LABELS, SiteRules, SiteStats, site_stats


_SHORT = {"fetch": "Save", "metadata": "Titles", "login": "Login", "skip": "Never",
          "private": "Own network"}   # short names for the table (\u2022 = your own rule)


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""


class _Num(QTableWidgetItem):
    """A table cell that sorts by number, not text."""

    def __init__(self, n: float, text: Optional[str] = None):
        super().__init__(text if text is not None else f"{int(n):,}")
        self.setData(Qt.UserRole, n)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return (self.data(Qt.UserRole) or 0) < (other.data(Qt.UserRole) or 0)


class TopSitesChart(QWidget):
    """Horizontal bars: items per site; the brighter part is what's kept offline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[SiteStats] = []
        self.setMinimumHeight(160)
        self.setAccessibleName("Your biggest sites")

    def set_rows(self, rows: List[SiteStats]) -> None:
        self.rows = rows[:10]
        self.setAccessibleDescription("; ".join(
            f"{r.domain}: {r.items} items, {r.offline} offline" for r in self.rows))
        self.setMinimumHeight(24 + 18 * max(1, len(self.rows)))
        self.update()

    def paintEvent(self, _e) -> None:
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fg = pal.windowText().color()
        muted = QColor(fg); muted.setAlpha(70)
        accent = pal.highlight().color()
        label_w = min(220, max(120, self.width() // 3))
        bar_w = max(40, self.width() - label_w - 70)
        most = max(r.items for r in self.rows) or 1
        fm = p.fontMetrics()
        for i, r in enumerate(self.rows):
            y = 6 + i * 18
            p.setPen(fg)
            p.drawText(QRectF(0, y, label_w - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(r.domain, Qt.ElideMiddle, label_w - 8))
            w = bar_w * r.items / most
            p.setPen(Qt.NoPen)
            p.setBrush(muted); p.drawRoundedRect(QRectF(label_w, y + 3, w, 11), 3, 3)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(label_w, y + 3, w * r.coverage, 11), 3, 3)
            p.setPen(fg)
            p.drawText(QRectF(label_w + w + 6, y, 64, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{r.items:,}")
        p.end()


class SitesDialog(QDialog):
    show_site = Signal(str)              # show this site's items in the main list
    fetch_site = Signal(str, str)        # domain, "copy" | "check"

    COLS = ["Site", "Items", "Offline", "Gone", "Failed", "Last added", "Rule"]

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.rules = SiteRules(ctx.storage, getattr(ctx.config.settings,
                                                    "allow_private_addresses", False))
        self.setWindowTitle("Sites")
        self.resize(1000, 680)
        v = QVBoxLayout(self)

        self.summary = QLabel("")
        self.summary.setObjectName("PlanSummary")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.chart = TopSitesChart()
        v.addWidget(self.chart)
        legend = QLabel("Bars: items per site; the bright part is what you have offline.")
        legend.setObjectName("ReaderMeta")
        v.addWidget(legend)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Find a site…")
        self.filter.setAccessibleName("Find a site")
        self.filter.textChanged.connect(self._apply_filter)
        v.addWidget(self.filter)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)            # the site name wins
        for c in range(1, len(self.COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setAccessibleName("Sites")
        self.table.itemSelectionChanged.connect(self._select)
        self.table.doubleClicked.connect(lambda *_: self._show())
        split.addWidget(self.table)

        side = QWidget()
        side.setMaximumWidth(400)                # the table (site names) gets the room
        sv = QVBoxLayout(side)
        self.site_title = QLabel(""); self.site_title.setObjectName("GroupTitle")
        self.site_title.setWordWrap(True)
        sv.addWidget(self.site_title)
        self.site_numbers = QLabel(""); self.site_numbers.setWordWrap(True)
        sv.addWidget(self.site_numbers)
        self.rule_note = QLabel(""); self.rule_note.setWordWrap(True)
        self.rule_note.setObjectName("ReaderMeta")
        sv.addWidget(self.rule_note)
        form = QFormLayout()
        self.mode = QComboBox(); self.mode.setAccessibleName("What to do with this site")
        for key in ("fetch", "metadata", "login", "skip"):
            self.mode.addItem(MODE_LABELS[key], key)
        self.pace = QDoubleSpinBox(); self.pace.setRange(0.5, 600); self.pace.setSuffix(" s")
        self.pace.setAccessibleName("Seconds between two pages from this site")
        self.extractor = QComboBox(); self.extractor.setAccessibleName("Page text extractor")
        from ..web.extract import available_extractors
        self.extractor.addItem("As in Settings", None)
        for e in available_extractors():
            self.extractor.addItem("Built in" if e == "builtin" else e.capitalize(), e)
        form.addRow("Rule", self.mode)
        form.addRow("Wait between pages", self.pace)
        form.addRow("Text extractor", self.extractor)
        sv.addLayout(form)
        rb = QHBoxLayout()
        self.save_btn = QPushButton("Save rule"); self.save_btn.clicked.connect(self._save_rule)
        self.reset_btn = QPushButton("Back to default")
        self.reset_btn.clicked.connect(self._reset_rule)
        rb.addWidget(self.save_btn); rb.addWidget(self.reset_btn); rb.addStretch(1)
        sv.addLayout(rb)
        sv.addSpacing(8)
        self.show_btn = QPushButton("Show its items"); self.show_btn.clicked.connect(self._show)
        self.fetch_btn = QPushButton("Save its pages…")
        self.fetch_btn.clicked.connect(lambda: self._fetch("copy"))
        self.check_btn = QPushButton("Check its links…")
        self.check_btn.clicked.connect(lambda: self._fetch("check"))
        for b in (self.show_btn, self.fetch_btn, self.check_btn):
            sv.addWidget(b)
        sv.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        split.setSizes([640, 360])
        v.addWidget(split, 1)

        close = QPushButton("Close"); close.clicked.connect(self.close)
        hb = QHBoxLayout(); hb.addStretch(1); hb.addWidget(close)
        v.addLayout(hb)
        self.reload()

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        self.rules = SiteRules(self.ctx.storage, self.rules.allow_private)
        self.stats = {s.domain: s for s in site_stats(self.ctx)}
        rows = list(self.stats.values())
        items = sum(s.items for s in rows)
        off = sum(s.offline for s in rows)
        dead = sum(s.dead for s in rows)
        login = sum(s.items for s in rows if s.rule.mode == "login")
        self.summary.setText(
            f"{len(rows):,} sites, {items:,} items. {off:,} kept offline "
            f"({(off / items * 100 if items else 0):.0f}%). {dead:,} no longer load. "
            f"{login:,} are on sites that need login (saved with the browser extension).")
        self.chart.set_rows(rows)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, s in enumerate(rows):
            vals = [QTableWidgetItem(s.domain), _Num(s.items), _Num(s.offline,
                    f"{s.offline:,} ({s.coverage * 100:.0f}%)"), _Num(s.dead),
                    _Num(s.problems), QTableWidgetItem(_day(s.last)),
                    QTableWidgetItem(_SHORT.get(s.rule.mode, s.rule.mode)
                                     + ("" if s.rule.builtin else " \u2022"))]
            for c, it in enumerate(vals):
                self.table.setItem(i, c, it)
        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.DescendingOrder)
        if rows and not self.table.selectedItems():
            self._select_row(0)
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, bool(t) and t not in self.table.item(r, 0).text())

    def current_domain(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).text() if rows else None

    def _select_row(self, r: int) -> None:
        # Through the selection model: QTableView.selectRow does nothing in a
        # right-to-left window that hasn't been shown yet (Arabic, Urdu).
        from PySide6.QtCore import QItemSelectionModel
        idx = self.table.model().index(r, 0)
        sm = self.table.selectionModel()
        sm.setCurrentIndex(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self._select()

    def select_domain(self, domain: str) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == domain:
                self._select_row(r)
                return

    def _select(self) -> None:
        d = self.current_domain()
        on = d is not None
        for w in (self.mode, self.pace, self.extractor, self.save_btn, self.reset_btn,
                  self.show_btn, self.fetch_btn, self.check_btn):
            w.setEnabled(on)
        if not on:
            return
        s = self.stats[d]
        rule = self.rules.for_domain(d)
        self.site_title.setText(d)
        self.site_numbers.setText(
            f"{s.items:,} items, first {_day(s.first)}, last {_day(s.last)}.\n"
            f"{s.offline:,} kept offline, {s.dead:,} no longer load, "
            f"{s.problems:,} couldn’t be saved.")
        default = BUILTIN.get(d)
        self.rule_note.setText(rule.note or (
            "Your own rule." if not rule.builtin else
            "Built-in rule." if default else "Default: pages are saved, "
            f"{DEFAULT_PACE:g} seconds apart."))
        private = rule.mode == "private"
        i = self.mode.findData(rule.mode)
        self.mode.setCurrentIndex(i if i >= 0 else 0)
        self.pace.setValue(rule.pace)
        j = self.extractor.findData(rule.extractor)
        self.extractor.setCurrentIndex(j if j >= 0 else 0)
        for w in (self.mode, self.pace, self.extractor, self.save_btn):
            w.setEnabled(not private)
        self.reset_btn.setEnabled(not rule.builtin)
        self.fetch_btn.setEnabled(rule.fetches)

    def _save_rule(self) -> None:
        d = self.current_domain()
        if d:
            self.rules.set(d, self.mode.currentData(), self.pace.value(),
                           self.extractor.currentData())
            self.reload(); self.select_domain(d)

    def _reset_rule(self) -> None:
        d = self.current_domain()
        if d:
            self.rules.clear(d)
            self.reload(); self.select_domain(d)

    def _show(self) -> None:
        d = self.current_domain()
        if d:
            self.show_site.emit(d)

    def _fetch(self, mode: str) -> None:
        d = self.current_domain()
        if d:
            self.fetch_site.emit(d, mode)
