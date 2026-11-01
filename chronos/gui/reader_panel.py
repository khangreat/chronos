"""Right panel: the reader.

Design: the one raised surface in the window. A natural-language byline, the
title in serif, a compact action bar (one primary action, the rest quiet, rare
actions in a menu), a provenance trail showing how the item reached your
archive, then the text in a capped reading column, your notes, and related
items. Rendering only — the main window supplies data and handles signals.
"""

from __future__ import annotations

from html import escape
from typing import Dict, List, Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from ..core.models import Bookmark
from .i18n import tr

READING_WIDTH = 720  # px — keeps serif body lines near 70 characters

from ..services.describe import (  # noqa: F401  (re-exported)
    _KIND_WORD, _SOURCE_NAMES, _src, byline_for, provenance_sentences,
)


class ReaderPanel(QWidget):
    fetch_requested = Signal(int)
    favorite_toggled = Signal(int, bool)
    quote_requested = Signal(int, str)
    takeaway_requested = Signal(int)
    open_related = Signal(int)
    archive_requested = Signal(int)
    ia_requested = Signal(int)            # save to the Internet Archive

    def __init__(self, network_allowed: bool, parent=None):
        super().__init__(parent)
        self._bm: Optional[Bookmark] = None
        self._network_allowed = network_allowed
        self._t: Dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # kept for i18n compatibility; the card speaks for itself, so hidden
        self._section = QLabel(tr("section.reader"))
        self._section.setVisible(False)
        outer.addWidget(self._section)

        self.card = QWidget()
        self.card.setObjectName("Reader")
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(10)

        self.byline = QLabel("")
        self.byline.setObjectName("Byline")
        self.byline.setWordWrap(True)
        lay.addWidget(self.byline)

        self.title = QLabel("")
        self.title.setObjectName("ReaderTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.PlainText)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)

        # back-compat alias: older code/tests read `meta`
        self.meta = self.byline

        # -- action bar ----------------------------------------------------- #
        bar = QWidget(); bar.setObjectName("ActionBar")
        actions = QHBoxLayout(bar)
        actions.setContentsMargins(0, 4, 0, 2)
        actions.setSpacing(6)

        self.open_btn = QPushButton(tr("btn.open_original"))
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.setToolTip("Open in your browser (Ctrl+O)")
        self.open_btn.clicked.connect(self._open)
        actions.addWidget(self.open_btn)

        self.fetch_btn = QPushButton(tr("btn.fetch_content"))
        self.fetch_btn.setToolTip("Download the page text to read it here")
        self.fetch_btn.clicked.connect(self._fetch)
        actions.addWidget(self.fetch_btn)

        self.fav_btn = QToolButton()
        self.fav_btn.setObjectName("FavButton")
        self.fav_btn.setCheckable(True)
        self.fav_btn.setText("\u2606")
        self.fav_btn.setToolTip("Favourite (Ctrl+D)")
        self.fav_btn.clicked.connect(self._toggle_fav)
        self.fav_btn.setAccessibleName("Favourite")
        actions.addWidget(self.fav_btn)

        self.quote_btn = QPushButton(tr("reader.quote"))
        self.quote_btn.setToolTip(
            "Select text in the reader, then keep it as a citable quote (Ctrl+Shift+Q)")
        self.quote_btn.clicked.connect(self._quote)
        actions.addWidget(self.quote_btn)

        self.takeaway_btn = QPushButton(tr("reader.takeaway"))
        self.takeaway_btn.setToolTip(
            "Write the one point you want to remember from this (Ctrl+Shift+T)")
        self.takeaway_btn.clicked.connect(self._takeaway)
        actions.addWidget(self.takeaway_btn)
        actions.addStretch(1)

        self.more_btn = QToolButton()
        self.more_btn.setObjectName("MoreButton")
        self.more_btn.setText("\u22ef")
        self.more_btn.setToolTip("More actions")
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_btn.setAccessibleName("More actions")
        menu = QMenu(self.more_btn)
        self.archive_btn = QAction(tr("btn.archive_offline"), menu)
        self.archive_btn.triggered.connect(self._archive)
        self.copy_link_act = QAction(tr("reader.copy_link"), menu)
        self.copy_link_act.triggered.connect(self._copy_link)
        menu.addAction(self.archive_btn)
        self.ia_act = QAction("Save to the Internet Archive", menu)
        self.ia_act.triggered.connect(
            lambda: self._bm and self.ia_requested.emit(self._bm.id))
        self.wb_view_act = QAction("Open the archived copy", menu)
        self.wb_view_act.triggered.connect(
            lambda: self._bm and self._bm.wayback_url and
            QDesktopServices.openUrl(QUrl(self._bm.wayback_url)))
        self.at_view_act = QAction("Find it on archive.today", menu)
        self.at_save_act = QAction("Save it on archive.today", menu)
        from ..web.archive_org import archive_today_save, archive_today_view
        self.at_view_act.triggered.connect(
            lambda: self._bm and QDesktopServices.openUrl(QUrl(archive_today_view(self._bm.url))))
        self.at_save_act.triggered.connect(
            lambda: self._bm and QDesktopServices.openUrl(QUrl(archive_today_save(self._bm.url))))
        menu.addSeparator()
        for a in (self.ia_act, self.wb_view_act, self.at_view_act, self.at_save_act):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.copy_link_act)
        self.more_btn.setMenu(menu)
        actions.addWidget(self.more_btn)
        lay.addWidget(bar)
        self._bar = bar

        # -- provenance trail + tags --------------------------------------- #
        self.provenance = QLabel("")
        self.provenance.setObjectName("Provenance")
        self.provenance.setWordWrap(True)
        self.provenance.setTextFormat(Qt.RichText)
        lay.addWidget(self.provenance)

        self.tags = QLabel("")
        self.tags.setObjectName("Tags")
        self.tags.setWordWrap(True)
        lay.addWidget(self.tags)

        # -- reading column ------------------------------------------------- #
        wrap = QWidget(); wrap.setObjectName("BodyWrap")
        wl = QHBoxLayout(wrap); wl.setContentsMargins(0, 6, 0, 0)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setMaximumWidth(READING_WIDTH)
        self.body.setMinimumHeight(220)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body.setAccessibleName("Page text")
        self.body.setAccessibleDescription(
            "Select text here, then use Quote to keep it with its citation.")
        wl.addWidget(self.body, 1)
        wl.addStretch(0)
        lay.addWidget(wrap, 1)

        # -- your notes + related ------------------------------------------ #
        self.quote_count = QLabel("")
        self.quote_count.setObjectName("ReaderMeta")
        lay.addWidget(self.quote_count)

        self.videos_header = QLabel("")
        self.videos_header.setObjectName("SubHead")
        lay.addWidget(self.videos_header)
        self.videos_list = QListWidget()
        self.videos_list.setObjectName("RelatedList")
        self.videos_list.setMaximumHeight(96)
        self.videos_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.videos_list.setCursor(Qt.PointingHandCursor)
        self.videos_list.setAccessibleName("Videos")
        self.videos_list.itemActivated.connect(self._on_related)
        self.videos_list.itemClicked.connect(self._on_related)
        lay.addWidget(self.videos_list)

        self.related_header = QLabel(tr("reader.related"))
        self.related_header.setObjectName("SubHead")
        lay.addWidget(self.related_header)
        self.related_list = QListWidget()
        self.related_list.setObjectName("RelatedList")
        self.related_list.setMaximumHeight(118)
        self.related_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.related_list.setCursor(Qt.PointingHandCursor)
        self.related_list.setAccessibleName("Related items in your archive")
        self.related_list.itemActivated.connect(self._on_related)
        self.related_list.itemClicked.connect(self._on_related)
        lay.addWidget(self.related_list)

        outer.addWidget(self.card, 1)
        self._clear()

    # -- state -------------------------------------------------------------- #
    def set_tokens(self, tokens: Dict[str, str]) -> None:
        self._t = dict(tokens)
        if self._bm is not None:
            self.show_bookmark(self._bm)

    def _c(self, key: str, fallback: str) -> str:
        return self._t.get(key, fallback)

    def _px(self, n: int) -> int:
        from .theme.tokens import scaled
        return scaled(self._t, n) if self._t else n

    def _set_open(self, is_open: bool) -> None:
        """Header and actions only exist when something is open."""
        for w in (self.byline, self.title, self._bar):
            w.setVisible(is_open)

    def show_welcome(self) -> None:
        self._bm = None
        self._set_open(False)
        self.provenance.setVisible(False)
        self.tags.setVisible(False)
        self.quote_count.setText("")
        self.set_related([])
        muted = self._c("text_muted", "#9AA1B2")
        faint = self._c("text_faint", "#6B7280")
        steps = [(tr(f"welcome.{k}_h"), tr(f"welcome.{k}_d"))
                 for k in ("import", "exports", "capture")]
        items = "".join(
            f"<p style='margin-bottom:14px'><span style='color:{muted};font-size:{self._px(15)}px'>"
            f"{escape(h)}</span><br><span style='color:{faint};font-size:{self._px(13)}px'>"
            f"{escape(d)}</span></p>" for h, d in steps)
        self.body.setHtml(
            f"<div style='margin-top:18px'>"
            f"<p style='font-size:{self._px(20)}px;color:{self._c('text', '#E6E8EE')};"
            f"margin-bottom:18px'>{escape(tr('welcome.title'))}</p>{items}</div>")

    def _clear(self) -> None:
        self._set_open(False)
        self.byline.setText("")
        self.provenance.setText("")
        self.tags.setText("")
        self.body.setHtml(self._empty_html(tr("reader.empty_title"),
                                           tr("reader.empty_hint")))
        self.quote_count.setText("")
        self.set_related([])
        self.set_videos("", [])
        for b in (self.open_btn, self.fav_btn, self.quote_btn, self.takeaway_btn,
                  self.more_btn):
            b.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setVisible(False)
        self.archive_btn.setEnabled(False)

    def show_bookmark(self, bm: Bookmark) -> None:
        self._bm = bm
        self._set_open(True)
        self.byline.setText(byline_for(bm))
        self.title.setText(bm.title or bm.url)
        self.tags.setText("   ".join(f"#{t}" for t in (bm.tags or [])))
        self.tags.setVisible(bool(bm.tags))

        for b in (self.open_btn, self.fav_btn, self.quote_btn, self.takeaway_btn,
                  self.more_btn):
            b.setEnabled(True)
        web = (bm.url or "").startswith(("http://", "https://"))
        self.open_btn.setEnabled(web)
        self.copy_link_act.setEnabled(web)
        for a in (self.ia_act, self.at_view_act, self.at_save_act):
            a.setEnabled(web)
        self.wb_view_act.setEnabled(bool(bm.wayback_url))
        self.open_btn.setToolTip(
            "Open in your browser (Ctrl+O)" if web else
            "This item came from an account export and has no web address.")
        self.fav_btn.setChecked(bool(bm.is_favorite))
        self.fav_btn.setAccessibleName(
            "Remove from favourites" if bm.is_favorite else "Add to favourites")
        self.fav_btn.setText("\u2605" if bm.is_favorite else "\u2606")
        can_fetch = (self._network_allowed and not bm.has_content
                     and (bm.url or "").startswith(("http://", "https://")))
        self.fetch_btn.setEnabled(can_fetch)
        self.fetch_btn.setVisible(can_fetch)
        self.archive_btn.setEnabled(self._network_allowed)
        self.archive_btn.setText(
            tr("btn.archive_offline") if self._network_allowed
            else tr("btn.archive_offline") + "  (turn on networking first)")

        warn = ""
        if bm.is_dead:
            wb = (f" <a href='{bm.wayback_url}'>Read the archived copy</a>."
                  if bm.wayback_url else "")
            warn = (f"<p style='color:{self._c('danger', '#C87A6A')}'>"
                    f"This link no longer loads.{wb}</p>")

        if bm.page_text:                      # fetched, or text from an export
            self.body.setHtml(warn + self._render(bm))
        elif bm.excerpt:
            self.body.setHtml(
                warn + self._para(escape(bm.excerpt), "text_muted")
                + self._para(self._not_read_hint(), "text_faint", small=True))
        else:
            self.body.setHtml(warn + self._empty_html(tr("reader.not_read"),
                                                      self._not_read_hint()))

    def _not_read_hint(self) -> str:
        if self._bm is not None and not (self._bm.url or "").startswith(("http://", "https://")):
            return tr("reader.hint_no_page")
        return tr("reader.hint_fetch" if self._network_allowed else "reader.hint_offline")

    # -- rendering ---------------------------------------------------------- #
    def _para(self, html: str, color_key: str, small: bool = False) -> str:
        size = f"font-size:{self._px(13)}px;" if small else ""
        return (f"<p style='color:{self._c(color_key, '#9AA1B2')};{size}'>"
                f"{html}</p>")

    def _empty_html(self, head: str, line: str) -> str:
        return (f"<div style='margin-top:28px'>"
                f"<p style='font-size:{self._px(17)}px;color:{self._c('text_muted', '#9AA1B2')}'>"
                f"{escape(head)}</p>"
                f"<p style='font-size:{self._px(13)}px;color:{self._c('text_faint', '#6B7280')}'>"
                f"{escape(line)}</p></div>")

    def _render(self, bm: Bookmark) -> str:
        paras = "".join(
            f"<p style='line-height:165%; margin-bottom:12px'>{escape(p)}</p>"
            for p in (bm.page_text or "").split("\n") if p.strip())
        return paras or self._empty_html("Empty page", "The page had no readable text.")

    def set_provenance(self, entries: List[str]) -> None:
        """entries: plain sentences, oldest first ('Bookmarked in Firefox, 3 Mar 2026')."""
        if not entries:
            self.provenance.setText("")
            self.provenance.setVisible(False)
            return
        dot = (f"<span style='color:{self._c('accent', '#C8A15A')}'>"
               f"\u25cf</span>&nbsp;")
        self.provenance.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join(
            dot + escape(e) for e in entries))
        self.provenance.setVisible(True)

    # -- notes + related ---------------------------------------------------- #
    def set_quote_count(self, n: int) -> None:
        self.set_notes(n, 0)

    def set_notes(self, quotes: int, takeaways: int) -> None:
        self._notes = (quotes, takeaways)
        bits = []
        if quotes:
            bits.append(tr("reader.quote_one") if quotes == 1
                        else tr("reader.quote_many", n=quotes))
        if takeaways:
            bits.append(tr("reader.takeaway_one") if takeaways == 1
                        else tr("reader.takeaway_many", n=takeaways))
        self.quote_count.setText(
            tr("reader.notes", what=tr("reader.and").join(bits)) if bits else "")

    def set_meta_text(self, text: str) -> None:
        self.quote_count.setText(text or "")

    def set_videos(self, header: str, items) -> None:
        """items: list of (label, bookmark_id). Hidden when empty."""
        self.videos_list.clear()
        for label, bid in items:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, bid)
            self.videos_list.addItem(it)
        self.videos_header.setText(header)
        has = bool(items)
        self.videos_header.setVisible(has)
        self.videos_list.setVisible(has)

    def set_related(self, items) -> None:
        """items: list of (title, bookmark_id). Hidden when empty."""
        self.related_list.clear()
        for title, bid in items:
            it = QListWidgetItem(title or "(untitled)")
            it.setData(Qt.UserRole, bid)
            self.related_list.addItem(it)
        has = bool(items)
        self.related_header.setVisible(has)
        self.related_list.setVisible(has)

    def _on_related(self, item) -> None:
        bid = item.data(Qt.UserRole)
        if bid is not None:
            self.open_related.emit(int(bid))

    # -- actions ------------------------------------------------------------ #
    def _open(self) -> None:
        if self._bm:
            QDesktopServices.openUrl(QUrl(self._bm.url))

    def _copy_link(self) -> None:
        if self._bm:
            QGuiApplication.clipboard().setText(self._bm.url)

    def _fetch(self) -> None:
        if self._bm and self._bm.id is not None:
            self.fetch_requested.emit(self._bm.id)

    def _toggle_fav(self) -> None:
        if self._bm and self._bm.id is not None:
            self.favorite_toggled.emit(self._bm.id, not self._bm.is_favorite)

    def _quote(self) -> None:
        if not (self._bm and self._bm.id is not None):
            return
        text = self.body.textCursor().selectedText().replace("\u2029", "\n").strip()
        self.quote_requested.emit(self._bm.id, text)

    def _takeaway(self) -> None:
        if self._bm is not None and self._bm.id is not None:
            self.takeaway_requested.emit(self._bm.id)

    def _archive(self) -> None:
        if self._bm and self._bm.id is not None:
            self.archive_requested.emit(self._bm.id)

    def set_network_allowed(self, allowed: bool) -> None:
        self._network_allowed = allowed
        if self._bm is not None:
            self.show_bookmark(self._bm)
        self.fetch_btn.setToolTip(
            "Download the page text to read it here" if allowed else
            "Networking is off. Turn on page fetching in Settings.")

    def retranslate(self) -> None:
        self._section.setText(tr("section.reader"))
        self.open_btn.setText(tr("btn.open_original"))
        self.fetch_btn.setText(tr("btn.fetch_content"))
        self.archive_btn.setText(tr("btn.archive_offline"))
        self.quote_btn.setText(tr("reader.quote"))
        self.takeaway_btn.setText(tr("reader.takeaway"))
        self.copy_link_act.setText(tr("reader.copy_link"))
        self.related_header.setText(tr("reader.related"))
        if self._bm is not None:
            self.show_bookmark(self._bm)
            self.set_notes(*getattr(self, "_notes", (0, 0)))
        else:
            self._clear()
