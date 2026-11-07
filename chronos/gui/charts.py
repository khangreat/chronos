"""Small charts drawn with the window's own colours (no chart library):
labelled horizontal bars, readable at any text size, described for screen
readers (the numbers are also in the text beside them)."""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class BarChart(QWidget):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.rows: List[Tuple[str, float]] = []
        self.setAccessibleName(title or "Chart")

    def set_rows(self, rows: List[Tuple[str, float]]) -> None:
        self.rows = list(rows)
        self.setAccessibleDescription("; ".join(f"{a}: {b:,.0f}" for a, b in self.rows))
        line = self.fontMetrics().height() + 4
        self.setMinimumHeight((1 if self.title else 0) * line + line * max(1, len(self.rows)) + 4)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fg = self.palette().windowText().color()
        bar = self.palette().highlight().color()
        track = QColor(fg); track.setAlpha(40)
        fm = p.fontMetrics()
        line = fm.height() + 4
        y = 0
        if self.title:
            f = p.font(); f.setBold(True); p.setFont(f)
            p.setPen(fg); p.drawText(QRectF(0, 0, self.width(), line), Qt.AlignLeft, self.title)
            f.setBold(False); p.setFont(f)
            y += line
        if not self.rows:
            p.end(); return
        label_w = min(max(fm.horizontalAdvance(a) for a, _ in self.rows) + 10,
                      self.width() // 3)
        num_w = max(fm.horizontalAdvance(f"{b:,.0f}") for _, b in self.rows) + 10
        bar_w = max(30, self.width() - label_w - num_w)
        most = max(b for _, b in self.rows) or 1
        for a, b in self.rows:
            p.setPen(fg)
            p.drawText(QRectF(0, y, label_w - 8, line), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(a, Qt.ElideRight, label_w - 8))
            p.setPen(Qt.NoPen)
            p.setBrush(track); p.drawRoundedRect(QRectF(label_w, y + 4, bar_w, line - 8), 3, 3)
            p.setBrush(bar)
            p.drawRoundedRect(QRectF(label_w, y + 4, max(2, bar_w * b / most), line - 8), 3, 3)
            p.setPen(fg)
            p.drawText(QRectF(label_w + bar_w + 6, y, num_w, line), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{b:,.0f}")
            y += line
        p.end()
