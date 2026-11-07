"""Your archive — what's in it, how safe it is, and what space it takes.

Overview:     the numbers (items, sites, kept offline, gone, quotes,
              takeaways…) and charts: per year, the last 12 months, kinds,
              where things came from, your top tags.
Safekeeping:  backups (daily, before risky changes, yours, full .zip),
              restore, and a health check with repairs that never delete.
Storage:      what takes space, per site; compact the database; clear
              removed files.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from ..services.safekeeping import size_text
from ..services.stats_service import overview
from .charts import BarChart


def _tile(value: str, label: str) -> QWidget:
    w = QWidget(); w.setObjectName("StatTile")
    v = QVBoxLayout(w); v.setContentsMargins(10, 8, 10, 8); v.setSpacing(0)
    a = QLabel(value); a.setObjectName("StatValue")
    b = QLabel(label); b.setObjectName("ReaderMeta"); b.setWordWrap(True)
    v.addWidget(a); v.addWidget(b)
    w.setAccessibleName(f"{label}: {value}")
    return w


class ArchiveDialog(QDialog):
    restored = Signal()                    # the archive changed under the window

    def __init__(self, ctx, parent=None, tab: str = "overview"):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Your archive")
        self.resize(860, 680)
        self._jobs = []
        self._last_report = None
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Your archive")
        v.addWidget(self.tabs)
        self._build_overview()
        self._build_safekeeping()
        self._build_storage()
        close = QPushButton("Close"); close.clicked.connect(self.close)
        hb = QHBoxLayout(); hb.addStretch(1); hb.addWidget(close)
        v.addLayout(hb)
        self.tabs.setCurrentIndex({"overview": 0, "safekeeping": 1, "storage": 2}.get(tab, 0))
        self.reload()

    # ------------------------------------------------------------------ #
    def _run(self, fn, ok, busy_label: QLabel, busy: str) -> None:
        from .workers import Job
        busy_label.setText(busy)
        j = Job(self.ctx.config.app_dir, fn, self)
        j.done.connect(ok)
        j.failed.connect(lambda m: busy_label.setText(f"Couldn’t finish: {m}"))
        self._jobs.append(j)
        j.start()

    def reload(self) -> None:
        self._fill_overview()
        self._fill_backups()
        self._fill_storage()

    # -- overview ------------------------------------------------------------ #
    def _build_overview(self) -> None:
        page = QWidget(); v = QVBoxLayout(page)
        self.tiles = QGridLayout(); self.tiles.setSpacing(8)
        v.addLayout(self.tiles)
        charts = QGridLayout(); charts.setSpacing(16)
        self.ch_years = BarChart("Added per year")
        self.ch_months = BarChart("The last 12 months")
        self.ch_kinds = BarChart("Kinds")
        self.ch_sources = BarChart("Where they came from")
        self.ch_tags = BarChart("Your top tags")
        charts.addWidget(self.ch_years, 0, 0); charts.addWidget(self.ch_months, 0, 1)
        charts.addWidget(self.ch_kinds, 1, 0); charts.addWidget(self.ch_sources, 1, 1)
        charts.addWidget(self.ch_tags, 2, 0)
        v.addLayout(charts)
        v.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
        self.tabs.addTab(scroll, "Overview")

    def _fill_overview(self) -> None:
        from .timeline_panel import _KIND_PLURAL
        o = overview(self.ctx)
        while self.tiles.count():
            w = self.tiles.takeAt(0).widget()
            if w:
                w.deleteLater()
        pct = lambda a: f" ({a / o['items'] * 100:.0f}%)" if o["items"] else ""   # noqa: E731
        since = datetime.fromtimestamp(o["first"]).strftime("%Y") if o["first"] else "—"
        tiles = [(f"{o['items']:,}", f"items since {since}"), (f"{o['sites']:,}", "sites"),
                 (f"{o['offline']:,}", "kept offline" + pct(o["offline"])),
                 (f"{o['gone']:,}", "no longer load"), (f"{o['quotes']:,}", "quotes"),
                 (f"{o['takeaways']:,}", "takeaways"), (f"{o['favourites']:,}", "favourites"),
                 (f"{o['tags']:,}", "tags")]
        for i, (a, b) in enumerate(tiles):
            self.tiles.addWidget(_tile(a, b), i // 4, i % 4)
        self.ch_years.set_rows(o["by_year"][-15:])
        self.ch_months.set_rows(o["last_months"])
        self.ch_kinds.set_rows([(_KIND_PLURAL.get(k, k), n) for k, n in o["by_kind"]])
        self.ch_sources.set_rows(o["by_source"])
        self.ch_tags.set_rows(o["top_tags"])
        self.overview_data = o

    # -- safekeeping ---------------------------------------------------------- #
    def _build_safekeeping(self) -> None:
        page = QWidget(); v = QVBoxLayout(page)
        intro = QLabel("Chronos backs up your archive every day it’s opened, and makes a "
                       "safety copy just before anything that removes or rewrites data. "
                       "Restoring always keeps a copy of how things are now, so you can "
                       "change your mind.")
        intro.setWordWrap(True); intro.setObjectName("ReaderMeta")
        v.addWidget(intro)
        self.backups = QListWidget(); self.backups.setAccessibleName("Backups")
        self.backups.itemSelectionChanged.connect(
            lambda: self.restore_btn.setEnabled(bool(self.backups.selectedItems())))
        v.addWidget(self.backups, 1)
        row = QHBoxLayout()
        self.backup_btn = QPushButton("Back up now"); self.backup_btn.clicked.connect(self._backup)
        self.full_btn = QPushButton("Full backup to a folder…")
        self.full_btn.setToolTip("Database, settings and every saved page in one .zip — "
                                 "for a USB stick or another drive.")
        self.full_btn.clicked.connect(self._full)
        self.restore_btn = QPushButton("Restore…"); self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._restore)
        self.from_file_btn = QPushButton("Restore from a file…")
        self.from_file_btn.clicked.connect(self._restore_file)
        self.open_btn = QPushButton("Open the backups folder")
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.ctx.safekeeping.dir))))
        for b in (self.backup_btn, self.full_btn, self.restore_btn, self.from_file_btn,
                  self.open_btn):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.backup_status = QLabel(""); self.backup_status.setWordWrap(True)
        v.addWidget(self.backup_status)

        h = QLabel("Health"); h.setObjectName("GroupTitle"); v.addWidget(h)
        hr = QHBoxLayout()
        self.check_btn = QPushButton("Check now"); self.check_btn.clicked.connect(
            lambda: self._check(False))
        self.deep_btn = QPushButton("Thorough check")
        self.deep_btn.setToolTip("Also reads every saved page and verifies it.")
        self.deep_btn.clicked.connect(lambda: self._check(True))
        self.repair_btn = QPushButton("Repair"); self.repair_btn.setEnabled(False)
        self.repair_btn.setToolTip("Rebuilds the search index, brings back set-aside files, "
                                   "moves unused files aside. Never deletes. A safety copy first.")
        self.repair_btn.clicked.connect(self._repair)
        for b in (self.check_btn, self.deep_btn, self.repair_btn):
            hr.addWidget(b)
        hr.addStretch(1)
        v.addLayout(hr)
        self.health = QPlainTextEdit(); self.health.setReadOnly(True)
        self.health.setAccessibleName("Health report")
        self.health.setPlaceholderText("Not checked yet.")
        self.health.setMaximumHeight(180)
        v.addWidget(self.health)
        self.tabs.addTab(page, "Safekeeping")

    def _fill_backups(self) -> None:
        self.backups.clear()
        for b in self.ctx.safekeeping.list():
            it = QListWidgetItem(f"{b.label}    {size_text(b.size)}")
            it.setData(Qt.UserRole, str(b.path))
            self.backups.addItem(it)
        if not self.backups.count():
            self.backups.addItem("No backups yet — the first is made today.")
            self.backups.item(0).setFlags(Qt.NoItemFlags)

    def _backup(self) -> None:
        p = self.ctx.safekeeping.backup("manual")
        self.backup_status.setText(f"Backed up: {p.name}")
        self._fill_backups(); self._fill_storage()

    def _full(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Full backup: choose a folder")
        if not folder:
            return
        self.full_btn.setEnabled(False)

        def ok(path):
            self.full_btn.setEnabled(True)
            self.backup_status.setText(f"Full backup written: {path}")
        self._run(lambda c: str(c.safekeeping.full_backup(folder)), ok, self.backup_status,
                  "Writing the full backup (database, settings, every saved page)…")

    def _confirm_restore(self, what: str) -> bool:
        return QMessageBox.question(
            self, "Restore",
            f"Put your archive back as it was in {what}?\n\nChanges made since then are "
            "undone — but a safety copy of how it is now is made first, so you can "
            "restore that if you change your mind.") == QMessageBox.Yes

    def _do_restore(self, path: str) -> None:
        try:
            self.ctx.safekeeping.restore(path)
        except Exception as e:
            QMessageBox.warning(self, "Restore", f"Couldn’t restore: {e}")
            return
        self.backup_status.setText("Restored. A copy of how it was is in the list.")
        self.reload()
        self.restored.emit()

    def _restore(self) -> None:
        items = self.backups.selectedItems()
        if not items or not items[0].data(Qt.UserRole):
            return
        if self._confirm_restore(f"“{items[0].text().split('    ')[0]}”"):
            self._do_restore(items[0].data(Qt.UserRole))

    def _restore_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore from a backup file", "",
                                              "Chronos backups (*.db *.zip)")
        if path and self._confirm_restore(Path(path).name):
            self._do_restore(path)

    def _check(self, deep: bool) -> None:
        self.check_btn.setEnabled(False); self.deep_btn.setEnabled(False)

        def ok(report):
            self._last_report = report
            self.health.setPlainText(report.text())
            self.repair_btn.setEnabled(report.repairable)
            self.check_btn.setEnabled(True); self.deep_btn.setEnabled(True)
        lab = QLabel()
        self.health.setPlainText("Checking…")
        self._run(lambda c: c.safekeeping.check(deep=deep), ok, lab, "")

    def _repair(self) -> None:
        done = self.ctx.safekeeping.repair()
        self.health.setPlainText("\n".join(done) + "\n\n" + self.ctx.safekeeping.check().text())
        self.repair_btn.setEnabled(False)
        self._fill_backups(); self._fill_storage()

    # -- storage ---------------------------------------------------------------- #
    def _build_storage(self) -> None:
        page = QWidget(); v = QVBoxLayout(page)
        self.usage = QLabel(""); self.usage.setWordWrap(True)
        self.usage.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.usage)
        self.ch_space = BarChart("Saved pages per site (size before compression)")
        v.addWidget(self.ch_space)
        row = QHBoxLayout()
        self.compact_btn = QPushButton("Compact the database")
        self.compact_btn.setToolTip("Gives back the space removed items leave behind.")
        self.compact_btn.clicked.connect(self._compact)
        self.empty_btn = QPushButton("Clear removed files older than 30 days")
        self.empty_btn.clicked.connect(lambda: self._empty(30))
        self.empty_all_btn = QPushButton("Clear all removed files…")
        self.empty_all_btn.clicked.connect(lambda: self._empty(None))
        self.folder_btn = QPushButton("Open the archive folder")
        self.folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.ctx.config.app_dir))))
        for b in (self.compact_btn, self.empty_btn, self.empty_all_btn, self.folder_btn):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.storage_status = QLabel(""); v.addWidget(self.storage_status)
        v.addStretch(1)
        self.tabs.addTab(page, "Storage")

    def _fill_storage(self) -> None:
        u = self.ctx.safekeeping.usage()
        self.usage_data = u
        rows = [("The database (items, quotes, notes)", u["database"] + u["journal"]),
                (f"Saved pages ({u['saved_count']:,})", u["saved_pages"]),
                ("Removed, kept 30 days for Undo", u["removed"]),
                (f"Backups ({u['backup_count']:,})", u["backups"]),
                ("Site icons", u["favicons"])]
        total = sum(b for _, b in rows)
        self.usage.setText(
            "<table cellpadding='3'>" + "".join(
                f"<tr><td>{a}</td><td align='right'>{size_text(b)}</td></tr>" for a, b in rows)
            + f"<tr><td><b>Altogether</b></td><td align='right'><b>{size_text(total)}</b></td></tr>"
            + f"<tr><td>Free on this drive</td><td align='right'>{size_text(u['free'])}</td></tr>"
            "</table>" + f"<p>In {self.ctx.config.app_dir}</p>")
        self.ch_space.set_rows([(d or "—", raw / 1024) for d, n, raw in u["per_site"]])
        self.ch_space.title = "Saved pages per site (KB, before compression)"
        self.empty_btn.setEnabled(u["removed"] > 0)
        self.empty_all_btn.setEnabled(u["removed"] > 0)

    def _compact(self) -> None:
        saved = self.ctx.safekeeping.compact()
        self.storage_status.setText(f"Compacted: {size_text(saved)} given back.")
        self._fill_storage()

    def _empty(self, days) -> None:
        if days is None and QMessageBox.question(
                self, "Clear removed files",
                "Delete every removed file now? Undo and older backups can no longer bring "
                "back those pages.") != QMessageBox.Yes:
            return
        n = self.ctx.safekeeping.empty_removed(days)
        self.storage_status.setText(f"Cleared {n:,} removed file(s).")
        self._fill_storage()

    def closeEvent(self, e) -> None:
        for j in self._jobs:
            j.wait(60000)
        super().closeEvent(e)
