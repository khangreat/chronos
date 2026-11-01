"""Saved quotes viewer — lists captured quotes with their source citation and
lets the user copy a quote formatted for pasting (with a short reference line).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QTextBrowser, QVBoxLayout,
)


def _cite_line(source: dict) -> str:
    if not source:
        return ""
    bits = [source.get("title", "")]
    if source.get("container-title"):
        bits.append(source["container-title"])
    issued = source.get("issued", {}).get("date-parts", [[None]])[0]
    if issued and issued[0]:
        bits.append(str(issued[0]))
    if source.get("URL"):
        bits.append(source["URL"])
    return " · ".join(b for b in bits if b)


class QuotesDialog(QDialog):
    def __init__(self, quotes: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Captured quotes")
        self.resize(560, 460)
        self._quotes = quotes

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.list = QListWidget()
        for q in quotes:
            src = q.get("source") or {}
            label = f"{src.get('title', 'source')} — {q['quote'][:48]}"
            QListWidgetItem(label, self.list)
        self.list.currentRowChanged.connect(self._show)
        row.addWidget(self.list, 1)

        self.view = QTextBrowser()
        row.addWidget(self.view, 1)
        lay.addLayout(row, 1)

        btns = QHBoxLayout()
        self.copy_btn = QPushButton("Copy quote + citation")
        self.copy_btn.clicked.connect(self._copy)
        btns.addStretch(1); btns.addWidget(self.copy_btn)
        lay.addLayout(btns)

        if quotes:
            self.list.setCurrentRow(0)

    def _current(self) -> dict:
        i = self.list.currentRow()
        return self._quotes[i] if 0 <= i < len(self._quotes) else {}

    def formatted(self, q: dict) -> str:
        if not q:
            return ""
        cite = _cite_line(q.get("source") or {})
        note = f"\nNote: {q['note']}" if q.get("note") else ""
        loc = f" ({q['locator']})" if q.get("locator") else ""
        return f"\u201c{q['quote']}\u201d{loc}\n\u2014 {cite}{note}"

    def _show(self, _row: int) -> None:
        self.view.setPlainText(self.formatted(self._current()))

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.formatted(self._current()))
