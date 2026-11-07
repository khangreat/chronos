"""The Fetch window — save offline copies or check links, for everything, a
selection or one site; see the plan before starting; pause, resume, stop.

The work runs on a background thread with its own connection to your archive;
the window only shows progress, so Chronos never freezes.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QRadioButton, QVBoxLayout)

from ..core.context import ApplicationContext
from ..web.fetch_queue import STATUS_LABELS, FetchEngine


class FetchRun(QThread):
    progress = Signal(int, int, str, str)       # done, total, site, status
    finished_text = Signal(str)
    failed = Signal(str)

    def __init__(self, app_dir: Path, mode: str, ids: Optional[List[int]],
                 domain: Optional[str], again: bool, parent=None):
        super().__init__(parent)
        self.args = (Path(app_dir), mode, ids, domain, again)
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()

    def run(self) -> None:
        app_dir, mode, ids, domain, again = self.args
        ctx = None
        try:
            ctx = ApplicationContext.for_dir(app_dir)
            eng = FetchEngine(ctx)
            plan = eng.plan(ids, mode, domain, again)
            res = eng.run(plan,
                          progress=lambda d, t, j, o: self.progress.emit(d, t, j.domain, o.status),
                          should_stop=self.stop_flag.is_set, paused=self.pause_flag.is_set)
            self.finished_text.emit(res.summary())
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            if ctx is not None:
                ctx.close()


class FetchDialog(QDialog):
    def __init__(self, ctx, parent=None, ids: Optional[List[int]] = None,
                 domain: Optional[str] = None, mode: str = "copy"):
        super().__init__(parent)
        self.ctx, self.ids, self.domain = ctx, ids, domain
        self.run_thread: Optional[FetchRun] = None
        self.setWindowTitle("Fetch pages")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        intro = QLabel("Chronos visits each site politely — one page at a time per "
                       "site, a few seconds apart — and skips sites that need you "
                       "logged in. You can pause or stop at any time; stopped runs "
                       "continue where they left off.")
        intro.setWordWrap(True); intro.setObjectName("ReaderMeta")
        v.addWidget(intro)

        row = QHBoxLayout()
        self.copy = QRadioButton("Save offline copies")
        self.check = QRadioButton("Check links still work")
        grp = QButtonGroup(self); grp.addButton(self.copy); grp.addButton(self.check)
        (self.check if mode == "check" else self.copy).setChecked(True)
        row.addWidget(self.copy); row.addWidget(self.check); row.addStretch(1)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Which:"))
        self.which = QComboBox()
        self.which.setAccessibleName("Which items")
        self.which.addItem("Everything in your archive", ("all", None))
        if ids:
            self.which.addItem(f"The {len(ids):,} selected item{'s' if len(ids) != 1 else ''}",
                               ("ids", None))
        if domain:
            self.which.addItem(f"Everything from {domain}", ("site", domain))
        self.which.setCurrentIndex(self.which.count() - 1)
        row2.addWidget(self.which, 1)
        v.addLayout(row2)

        self.again = QCheckBox("Also try again items already saved, or refused recently")
        v.addWidget(self.again)

        self.plan_label = QLabel("")
        self.plan_label.setWordWrap(True)
        self.plan_label.setObjectName("PlanSummary")
        v.addWidget(self.plan_label)

        self.net_note = QLabel("")
        self.net_note.setWordWrap(True)
        self.net_note.setObjectName("FetchNote")
        v.addWidget(self.net_note)

        self.bar = QProgressBar(); self.bar.setVisible(False)
        self.bar.setAccessibleName("Progress")
        v.addWidget(self.bar)
        self.live = QLabel(""); self.live.setWordWrap(True)
        v.addWidget(self.live)
        self.result = QPlainTextEdit(); self.result.setReadOnly(True)
        self.result.setVisible(False); self.result.setMinimumHeight(140)
        self.result.setAccessibleName("Result")
        v.addWidget(self.result)

        btns = QHBoxLayout()
        self.settings_btn = QPushButton("Open Settings…")
        self.settings_btn.clicked.connect(self._open_settings)
        btns.addWidget(self.settings_btn)
        btns.addStretch(1)
        self.start_btn = QPushButton("Start"); self.start_btn.setObjectName("PrimaryButton")
        self.pause_btn = QPushButton("Pause"); self.pause_btn.setEnabled(False)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        for b in (self.start_btn, self.pause_btn, self.stop_btn, self.close_btn):
            btns.addWidget(b)
        v.addLayout(btns)
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self._pause)
        self.stop_btn.clicked.connect(self._stop)
        self.close_btn.clicked.connect(self.close)
        for w in (self.copy, self.check):
            w.toggled.connect(self.refresh_plan)
        self.which.currentIndexChanged.connect(self.refresh_plan)
        self.again.toggled.connect(self.refresh_plan)
        self.refresh_plan()

    # ------------------------------------------------------------------ #
    @property
    def mode(self) -> str:
        return "check" if self.check.isChecked() else "copy"

    def _scope(self):
        kind, dom = self.which.currentData()
        return (self.ids if kind == "ids" else None), (dom if kind == "site" else None)

    def refresh_plan(self) -> None:
        ids, dom = self._scope()
        eng = FetchEngine(self.ctx)
        self.plan = eng.plan(ids, self.mode, dom, self.again.isChecked())
        self.plan_label.setText(self.plan.summary())
        try:
            eng.require(self.mode)
            self.net_note.setText(""); self.net_note.setVisible(False)
            ok = True
        except Exception:
            what = ("\u201cCheck for dead links\u201d" if self.mode == "check"
                    else "\u201cFetch page content\u201d")
            self.net_note.setText(
                f"Chronos is offline for this. In Settings, turn on \u201cEnable "
                f"networking\u201d and {what}, then come back.")
            self.net_note.setVisible(True)
            ok = False
        self.settings_btn.setVisible(not ok)
        self.start_btn.setEnabled(ok and bool(self.plan.jobs) and self.run_thread is None)

    def _open_settings(self) -> None:
        p = self.parent()
        if p is not None and hasattr(p, "_open_settings"):
            p._open_settings()
        self.ctx.network.settings = self.ctx.config.settings
        self.refresh_plan()

    def start(self) -> None:
        ids, dom = self._scope()
        self.ctx.storage.conn.commit()     # the run reads the archive on its own connection
        self.started_at = time.monotonic()
        self.bar.setVisible(True); self.bar.setRange(0, max(1, len(self.plan.jobs)))
        self.bar.setValue(0)
        self.result.setVisible(False)
        self.counts = {}
        self.run_thread = FetchRun(self.ctx.config.app_dir, self.mode, ids, dom,
                                   self.again.isChecked(), self)
        self.run_thread.progress.connect(self._on_progress)
        self.run_thread.finished_text.connect(self._on_done)
        self.run_thread.failed.connect(self._on_failed)
        for w in (self.start_btn, self.copy, self.check, self.which, self.again):
            w.setEnabled(False)
        self.pause_btn.setEnabled(True); self.stop_btn.setEnabled(True)
        self.live.setText("Starting…")
        self.run_thread.start()

    def _on_progress(self, done: int, total: int, site: str, status: str) -> None:
        self.bar.setValue(done)
        self.counts[status] = self.counts.get(status, 0) + 1
        parts = ", ".join(f"{STATUS_LABELS.get(k, k)} {n:,}" for k, n in
                          sorted(self.counts.items(), key=lambda kv: -kv[1]))
        el = time.monotonic() - self.started_at
        eta = ""
        if done >= 5 and done < total:
            left = el / done * (total - done)
            eta = f" — about {int(left // 60)} min left" if left >= 60 else \
                " — under a minute left"
        self.live.setText(f"{done:,} of {total:,}{eta}. Last: {site}. {parts}")

    def _pause(self) -> None:
        t = self.run_thread
        if t is None:
            return
        if t.pause_flag.is_set():
            t.pause_flag.clear(); self.pause_btn.setText("Pause")
        else:
            t.pause_flag.set(); self.pause_btn.setText("Resume")
            self.live.setText(self.live.text() + "  (paused)")

    def _stop(self) -> None:
        if self.run_thread is not None:
            self.run_thread.pause_flag.clear()
            self.run_thread.stop_flag.set()
            self.stop_btn.setEnabled(False)
            self.live.setText("Stopping after the pages already on their way…")

    def _finish(self) -> None:
        self.run_thread = None
        for w in (self.copy, self.check, self.which, self.again):
            w.setEnabled(True)
        self.pause_btn.setEnabled(False); self.pause_btn.setText("Pause")
        self.stop_btn.setEnabled(False)
        self.refresh_plan()
        p = self.parent()
        if p is not None and hasattr(p, "_reload_views"):
            p._reload_views()

    def _on_done(self, text: str) -> None:
        self.result.setPlainText(text); self.result.setVisible(True)
        self.live.setText("Done.")
        self._finish()

    def _on_failed(self, msg: str) -> None:
        self.result.setPlainText(msg); self.result.setVisible(True)
        self.live.setText("Couldn’t run.")
        self._finish()

    def closeEvent(self, e) -> None:
        if self.run_thread is not None:              # stop cleanly, never mid-write
            self.run_thread.stop_flag.set()
            self.run_thread.wait(30000)
        super().closeEvent(e)
