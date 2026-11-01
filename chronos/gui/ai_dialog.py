"""Ask AI about selected items.

Shows exactly what will be sent and where: the number of items, whether the
model is on this computer or elsewhere, and the model's name. The answer can be
copied, saved as a Markdown file, or kept as a takeaway on every item it covers
(so the AI's reading of your sources lives in your archive, marked as such).
"""

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QTextBrowser, QVBoxLayout,
)

from ..ai import client
from ..ai.pack import TASK_LABELS, build_messages, build_pack
from .workers import TaskWorker


_REF = re.compile(r"(?<![\\\]])\[(\d{1,3})\](?!\()")


def link_references(markdown: str, count: int) -> str:
    """Turn the AI's [n] references into links to the items they name."""
    def sub(m):
        n = int(m.group(1))
        return (f"[\\[{n}\\]](chronos-item:{n})" if 1 <= n <= count else m.group(0))
    return _REF.sub(sub, markdown)


class AskAIDialog(QDialog):
    takeaways_saved = Signal(int)
    open_item = Signal(int)            # bookmark id of a cited [n]

    def __init__(self, ctx, ids: List[int], parent=None, sync: bool = False):
        super().__init__(parent)
        self.ctx = ctx
        self.ids = list(ids)
        self._sync = sync
        self._worker: Optional[TaskWorker] = None
        self.answer_text = ""
        self.pack = build_pack(ctx, self.ids)
        n = len(self.pack.ids)
        self.setWindowTitle(f"Ask AI about {n} item{'s' if n != 1 else ''}")
        self.resize(760, 680)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)

        st = ctx.config.settings
        endpoint = (st.ai_endpoint or "").rstrip("/")
        local = client.is_local(endpoint)
        where = ("a model on this computer" if local
                 else f"an AI service at {endpoint.split('/')[2] if '//' in endpoint else endpoint}")
        self.where = QLabel(
            f"Sends {n} item{'s' if n != 1 else ''} (titles, links, your quotes and "
            f"takeaways, and their text) to {where}"
            + (f", model {st.ai_model}." if st.ai_model else "."))
        self.where.setObjectName("ReaderMeta")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        if self.pack.truncated:
            t = QLabel("Long texts are shortened to fit; your quotes and takeaways are "
                       "always included in full.")
            t.setObjectName("ReaderMeta"); t.setWordWrap(True); lay.addWidget(t)

        row = QHBoxLayout()
        self.task = QComboBox()
        for key, label in TASK_LABELS.items():
            self.task.addItem(label, key)
        self.task.setAccessibleName("What to ask")
        row.addWidget(QLabel("Task"))
        row.addWidget(self.task, 1)
        lay.addLayout(row)

        self.question = QPlainTextEdit()
        self.question.setPlaceholderText(
            "Your question, or anything to add (optional for the tasks above)")
        self.question.setMaximumHeight(90)
        self.question.setAccessibleName("Your question")
        lay.addWidget(self.question)

        go = QHBoxLayout()
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setObjectName("PrimaryButton")
        self.ask_btn.setDefault(True)
        self.ask_btn.clicked.connect(self.ask)
        self.status = QLabel("")
        self.status.setObjectName("ReaderMeta")
        self.status.setWordWrap(True)
        go.addWidget(self.ask_btn)
        go.addWidget(self.status, 1)
        lay.addLayout(go)

        self.answer = QTextBrowser()
        self.answer.setObjectName("AIAnswer")
        self.answer.setOpenLinks(False)
        self.answer.anchorClicked.connect(self._on_link)
        self.answer.setAccessibleName("Answer")
        self.answer.setAccessibleDescription(
            "Numbers in brackets refer to your items; activate one to open it.")
        lay.addWidget(self.answer, 1)

        keep = QHBoxLayout()
        self.copy_btn = QPushButton("Copy answer")
        self.copy_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.answer_text))
        self.save_btn = QPushButton("Save as file…")
        self.save_btn.clicked.connect(self._save_file)
        self.keep_btn = QPushButton("Keep as takeaway")
        self.keep_btn.setToolTip("Adds the answer as a takeaway, marked as written "
                                 "by AI, on each item it covers")
        self.keep_btn.clicked.connect(self.keep_as_takeaway)
        for b in (self.copy_btn, self.save_btn, self.keep_btn):
            b.setEnabled(False)
            keep.addWidget(b)
        keep.addStretch(1)
        close = QPushButton("Done"); close.clicked.connect(self.reject)
        keep.addWidget(close)
        lay.addLayout(keep)

        if not ctx.network.is_allowed(client.capability_for(endpoint)):
            self.ask_btn.setEnabled(False)
            self.status.setText(
                "AI is off. Turn it on in Settings, AI (Ctrl+,). Until then you can "
                "use Copy for AI and paste into any AI chat." if local else
                "This AI service is on another computer. To use it, turn on "
                "networking, AI and “Allow AI services on other computers” in "
                "Settings.")

    # -- asking ------------------------------------------------------------- #
    def ask(self) -> None:
        task = self.task.currentData()
        try:
            messages = build_messages(task, self.pack, self.question.toPlainText())
        except ValueError as e:
            self.status.setText(str(e))
            return
        self.ask_btn.setEnabled(False)
        self.status.setText("Waiting for the answer…")
        settings = self.ctx.config.settings
        fn = lambda c: client.chat(settings, c.network, messages)  # noqa: E731
        if self._sync:
            try:
                self._done(fn(self.ctx))
            except Exception as e:
                self._failed(str(e))
            return
        self._worker = TaskWorker(self.ctx.config.app_dir, fn, self)
        self._worker.done.connect(self._done)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() == "chronos-item":
            try:
                n = int(url.path() or url.toString().split(":", 1)[1])
            except (ValueError, IndexError):
                return
            if 1 <= n <= len(self.pack.ids):
                self.open_item.emit(self.pack.ids[n - 1])
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _show_answer(self, text: str) -> None:
        self.answer.setMarkdown(link_references(text, len(self.pack.ids)))
        # breathing room between paragraphs and list items
        cur = QTextCursor(self.answer.document())
        cur.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setBottomMargin(8)
        fmt.setLineHeight(140, 1)                    # 1 = ProportionalHeight
        cur.mergeBlockFormat(fmt)

    def _done(self, text: str) -> None:
        self.answer_text = text
        self._show_answer(text)
        self.status.setText("")
        self.ask_btn.setEnabled(True)
        self.ask_btn.setText("Ask again")
        for b in (self.copy_btn, self.save_btn, self.keep_btn):
            b.setEnabled(True)

    def _failed(self, msg: str) -> None:
        self.status.setText(msg)
        self.ask_btn.setEnabled(True)

    # -- keeping ------------------------------------------------------------ #
    def keep_as_takeaway(self) -> int:
        if not self.answer_text:
            return 0
        label = TASK_LABELS.get(self.task.currentData(), "AI")
        text = f"[AI · {label}] {self.answer_text}"
        for bid in self.pack.ids:
            self.ctx.takeaways.add(bid, text)
        self.keep_btn.setEnabled(False)
        self.status.setText(f"Kept on {len(self.pack.ids)} item(s).")
        self.takeaways_saved.emit(len(self.pack.ids))
        return len(self.pack.ids)

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save answer", "answer.md",
                                              "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.answer_text + "\n\n---\n\n" + self.pack.markdown)
            self.status.setText(f"Saved to {path}")
