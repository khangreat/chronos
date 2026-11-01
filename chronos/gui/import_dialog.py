"""Import window — every way into Chronos, in one place.

Built from the source catalogue (services/sources.py): browsers found on this
computer, social account exports, account packages, and plain files. Each row
says where to get the file and what to pick; imports run on a worker thread
with their own database connection, and report a one-line result in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..services.sources import GROUP_TITLES, Source, all_sources
from .workers import TaskWorker


class ImportDialog(QDialog):
    imported = Signal()          # something new landed: refresh the views

    def __init__(self, ctx, parent=None, sync: bool = False):
        super().__init__(parent)
        self.ctx = ctx
        self._sync = sync        # tests run imports inline
        self._workers = []
        self._status: Dict[str, QLabel] = {}
        self._buttons: Dict[str, list] = {}
        self.setWindowTitle("Add to your archive")
        self.resize(720, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(10)

        intro = QLabel("Bring in what you already have. Everything stays on this "
                       "computer; nothing is uploaded.")
        intro.setObjectName("ReaderMeta")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("BodyWrap")
        self._lay = QVBoxLayout(body)
        self._lay.setContentsMargins(0, 0, 8, 0)
        self._lay.setSpacing(4)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.sources = {s.id: s for s in all_sources()}
        groups: Dict[str, list] = {}
        for s in self.sources.values():
            groups.setdefault(s.group, []).append(s)
        for g in ("browsers", "files", "social", "packages"):
            self._section(GROUP_TITLES[g])
            if g == "browsers" and not groups.get(g):
                note = QLabel("No browser profiles were found on this computer. "
                              "Export bookmarks to an HTML file from your browser "
                              "and use “Bookmarks HTML file” below.")
                note.setObjectName("ReaderMeta")
                note.setWordWrap(True)
                self._lay.addWidget(note)
            for s in groups.get(g, []):
                self._row(s)
        self._lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).setText("Done")
        outer.addWidget(buttons)

    # -- layout ------------------------------------------------------------- #
    def _section(self, title: str) -> None:
        h = QLabel(title)
        h.setObjectName("GroupTitle")
        h.setContentsMargins(0, 14, 0, 2)
        self._lay.addWidget(h)

    def _row(self, s: Source) -> None:
        row = QWidget(); row.setObjectName("BodyWrap")
        rl = QHBoxLayout(row); rl.setContentsMargins(0, 6, 0, 6); rl.setSpacing(12)
        text = QWidget(); text.setObjectName("BodyWrap")
        tl = QVBoxLayout(text); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(2)
        name = QLabel(s.name)
        name.setObjectName("ItemName")
        f = name.font(); f.setWeight(f.Weight.DemiBold); name.setFont(f)
        how = QLabel(s.how)
        how.setObjectName("ReaderMeta")
        how.setWordWrap(True)
        status = QLabel("")
        status.setObjectName("Byline")
        status.setWordWrap(True)
        status.setVisible(False)
        tl.addWidget(name); tl.addWidget(how); tl.addWidget(status)
        rl.addWidget(text, 1)

        btns = []
        if s.pick == "none":
            b = QPushButton("Import")
            b.clicked.connect(lambda _=False, sid=s.id: self.run_source(sid, None))
            btns.append(b)
        if s.pick in ("file", "either"):
            b = QPushButton("Choose file…")
            b.clicked.connect(lambda _=False, sid=s.id: self._choose(sid, folder=False))
            btns.append(b)
        if s.pick in ("folder", "either"):
            b = QPushButton("Choose folder…" if s.pick == "folder" else "Folder…")
            b.clicked.connect(lambda _=False, sid=s.id: self._choose(sid, folder=True))
            btns.append(b)
        for b in btns:
            b.setAccessibleName(f"{s.name}: {b.text().rstrip(chr(0x2026))}")
            b.setAccessibleDescription(s.how)
            rl.addWidget(b, 0, Qt.AlignTop)
        name.setBuddy(btns[0]) if btns else None
        self._status[s.id] = status
        self._buttons[s.id] = btns
        self._lay.addWidget(row)

    # -- actions ------------------------------------------------------------ #
    def _choose(self, sid: str, folder: bool) -> None:
        s = self.sources[sid]
        if folder:
            path = QFileDialog.getExistingDirectory(self, f"{s.name}: choose folder")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, f"{s.name}: choose file", "",
                f"{s.file_filter};;All files (*)" if s.file_filter else "All files (*)")
        if path:
            self.run_source(sid, path)

    def _set_status(self, sid: str, text: str, error: bool = False) -> None:
        lab = self._status[sid]
        lab.setObjectName("Danger" if error else ("Byline" if text.endswith("\u2026")
                                                   else "Outcome"))
        lab.style().unpolish(lab); lab.style().polish(lab)
        lab.setText(text)
        lab.setVisible(bool(text))

    def _busy(self, sid: str, busy: bool) -> None:
        for b in self._buttons.get(sid, []):
            b.setEnabled(not busy)

    def run_source(self, sid: str, path: Optional[str]) -> None:
        s = self.sources[sid]
        self._busy(sid, True)
        self._set_status(sid, "Importing…")

        def finish_ok(msg: str) -> None:
            self._busy(sid, False)
            self._set_status(sid, "\u2713  " + msg)
            self.imported.emit()

        def finish_err(msg: str) -> None:
            self._busy(sid, False)
            self._set_status(sid, f"Couldn’t import this file. {msg}", error=True)

        fn = (lambda ctx, s=s, p=path: s.run(ctx, p))
        if self._sync:
            try:
                finish_ok(str(fn(self.ctx)))
            except Exception as e:
                finish_err(str(e))
            return
        w = TaskWorker(self.ctx.config.app_dir, fn, self)
        w.done.connect(finish_ok)
        w.failed.connect(finish_err)
        self._workers.append(w)
        w.start()

    def status_text(self, sid: str) -> str:
        return self._status[sid].text()
