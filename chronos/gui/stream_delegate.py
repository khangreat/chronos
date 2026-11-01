"""Stream delegate — paints rows and headers directly (no child widgets).

Row anatomy (designed for scanning, not for showing everything):
    title ............................................ ★
    site/domain                                      Post
    10 Mar 2026     #brahui  #phonology
Selection is a brass rule on the left plus a lifted surface — the timeline's
own visual language — rather than a grey slab. Colours come from the theme.
"""

from __future__ import annotations

from typing import Dict
from urllib.parse import urlsplit

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from .stream_model import ENTRY_ROLE
from .theme.tokens import scaled

HEADER_H = 34
ITEM_H = 70
PAD_X = 14

_KIND_WORD = {
    "social_post": "Post", "social_comment": "Comment", "thread": "Thread",
    "article": "Article", "feed_entry": "Feed", "image": "Image",
    "place": "Place", "product": "Product", "video": "Video", "search": "Search",
}


def _iso(text: str) -> str:
    """Unicode first-strong isolate: each run keeps its own direction, so a
    Latin tag or title renders correctly inside an RTL interface."""
    return "\u2068" + (text or "") + "\u2069"


def _domain(url: str) -> str:
    host = urlsplit(url or "").hostname or url or ""
    return host[4:] if host.startswith("www.") else host


class BookmarkDelegate(QStyledItemDelegate):
    def __init__(self, tokens: Dict[str, str], parent=None):
        super().__init__(parent)
        self.t = tokens
        self.suppress_header = ""   # header text equal to the pane title is redundant

    def sizeHint(self, option, index) -> QSize:
        entry = index.data(ENTRY_ROLE)
        if entry and entry.kind == "header":
            if self._redundant(entry.text):
                return QSize(option.rect.width(), 2)
            return QSize(option.rect.width(), round(HEADER_H * self.k))
        return QSize(option.rect.width(), round(ITEM_H * self.k))

    @property
    def k(self) -> float:
        return float(self.t.get("scale", 1.0))

    def _redundant(self, text: str) -> bool:
        return bool(self.suppress_header) and \
            text.strip().lower() == self.suppress_header.strip().lower()

    def _font(self, base, px, weight=None):
        f = QFont(base)
        f.setPixelSize(scaled(self.t, px))
        if weight is not None:
            f.setWeight(weight)
        return f

    def paint(self, painter, option, index) -> None:
        entry = index.data(ENTRY_ROLE)
        if entry is None:
            return
        direction = option.direction
        bounds = option.rect

        def V(rect: QRect) -> QRect:   # mirror geometry in RTL layouts
            return QStyle.visualRect(direction, bounds, rect)

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        r = option.rect

        if entry.kind == "header" and self._redundant(entry.text):
            painter.restore()
            return
        if entry.kind == "header":
            painter.setFont(self._font(option.font, 12, QFont.DemiBold))
            painter.setPen(QColor(self.t["text_muted"]))
            label = " ".join(w.capitalize() for w in entry.text.split())
            painter.drawText(V(QRect(r.left() + PAD_X, r.top() + 6,
                                     r.width() - 2 * PAD_X, r.height() - 6)),
                             Qt.AlignVCenter | Qt.AlignLeft, _iso(label))
            painter.restore()
            return

        b = entry.bookmark
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        card = r.adjusted(4, 2, -6, -2)
        if selected or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.t["surface_alt" if selected else "surface"]))
            painter.drawRoundedRect(card, 6, 6)
        if selected:
            painter.setBrush(QColor(self.t["accent"]))
            painter.drawRoundedRect(V(QRect(card.left(), card.top() + 8, 3,
                                            card.height() - 16)), 1.5, 1.5)

        inner = card.adjusted(PAD_X - 2, round(9 * self.k), -10, -round(9 * self.k))
        fav = bool(b and b.is_favorite)
        star_w = 16 if fav else 0

        # line 1 — title
        ft = self._font(option.font, 13, QFont.DemiBold if selected else QFont.Normal)
        painter.setFont(ft)
        painter.setPen(QColor(self.t["text"]))
        tw = inner.width() - star_w - (4 if fav else 0)
        fmt = QFontMetrics(ft)
        th = max(round(18 * self.k), fmt.height())
        ty = inner.top() + round(18 * self.k) - th      # grow upward into padding
        title = fmt.elidedText(b.title or b.url, Qt.ElideRight, tw)
        painter.drawText(V(QRect(inner.left(), ty, tw, th)),
                         Qt.AlignVCenter | Qt.AlignLeft, _iso(title))
        if fav:
            painter.setPen(QColor(self.t["accent"]))
            painter.drawText(V(QRect(inner.right() - star_w, inner.top(), star_w, round(18 * self.k))),
                             Qt.AlignVCenter | Qt.AlignRight, "\u2605")

        # line 2 — where it's from (left) and what it is (right)
        fs = self._font(option.font, 11)
        fms = QFontMetrics(fs)
        painter.setFont(fs)
        kind = _KIND_WORD.get(getattr(b, "kind", "webpage"), "")
        kind_w = fms.horizontalAdvance(kind) + 2 if kind else 0
        web = (b.url or "").startswith(("http://", "https://"))
        source = b.site_name or (_domain(b.url) if web else "From an account export")
        if b.is_dead:
            source = f"{source}   link no longer loads"
        painter.setPen(QColor(self.t["danger"] if b.is_dead else self.t["link"]))
        sw = inner.width() - kind_w - (10 if kind else 0)
        painter.drawText(V(QRect(inner.left(), inner.top() + round(20 * self.k), sw, round(15 * self.k))),
                         Qt.AlignVCenter | Qt.AlignLeft,
                         _iso(fms.elidedText(source, Qt.ElideRight, sw)))
        if kind:
            painter.setPen(QColor(self.t["text_muted"] if not selected
                                  else self.t["accent"]))
            painter.drawText(V(QRect(inner.right() - kind_w, inner.top() + round(20 * self.k), kind_w, round(15 * self.k))),
                             Qt.AlignVCenter | Qt.AlignRight, _iso(kind))

        # line 3 — date, then tags
        date = f"{b.dt.day} {b.dt:%b %Y}"
        dw = fms.horizontalAdvance(date)
        painter.setPen(QColor(self.t["text_faint"]))
        painter.drawText(V(QRect(inner.left(), inner.top() + round(37 * self.k), dw + 2, round(15 * self.k))),
                         Qt.AlignVCenter | Qt.AlignLeft, _iso(date))
        if b.tags:
            tags = "  ".join(_iso(f"#{t}") for t in b.tags[:4])
            avail = inner.width() - dw - 16
            painter.setPen(QColor(self.t["text_muted"]))
            painter.drawText(V(QRect(inner.left() + dw + 16, inner.top() + round(37 * self.k), avail, round(15 * self.k))),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             _iso(fms.elidedText(tags, Qt.ElideRight, avail)))
        painter.restore()
