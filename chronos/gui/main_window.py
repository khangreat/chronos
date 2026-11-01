"""MainWindow — composes the three panels over the Core and wires signals.

Layout: a top bar (brand + search), a horizontal splitter (spine · stream ·
reader), and a status bar. All data comes from the ApplicationContext; the
window holds no truth of its own.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core.models import Bookmark
from .i18n import tr
from .reader_panel import ReaderPanel
from .stream_panel import StreamPanel
from .timeline_panel import TimelinePanel
from .workers import FetchWorker


def _mn(text: str) -> str:
    """Give Latin-script menu text an Alt-key mnemonic (first letter)."""
    return f"&{text}" if text and text[0].isascii() and text[0].isalpha() else text


class MainWindow(QMainWindow):
    def __init__(self, ctx, tokens=None):
        super().__init__()
        self.ctx = ctx
        if tokens is None:
            from .theme.tokens import THEMES
            tokens = THEMES["dusk"]
        self.tokens = tokens
        self._worker = None
        self.setWindowTitle(f"Chronos Archive {__version__}")
        self.resize(1180, 760)
        self.setAcceptDrops(True)        # drop any export, folder or zip to bring it in

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        vlay = QVBoxLayout(root)
        vlay.setContentsMargins(14, 10, 14, 4)
        vlay.setSpacing(10)

        vlay.addWidget(self._build_topbar())

        self.splitter = QSplitter(Qt.Horizontal)
        self.timeline = TimelinePanel(ctx)
        self.stream = StreamPanel(self.tokens)
        self.reader = ReaderPanel(network_allowed=ctx.network.is_allowed("page_fetch"))
        self.reader.set_tokens(self.tokens)
        for w in (self.timeline, self.stream, self.reader):
            self.splitter.addWidget(w)
        # proportions: a narrow index, a scannable stream, a generous reader
        self.timeline.setMinimumWidth(150)
        self.stream.setMinimumWidth(280)
        self.reader.setMinimumWidth(460)
        for i in range(3):
            self.splitter.setCollapsible(i, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([180, 360, 740])
        vlay.addWidget(self.splitter, 1)

        self.setStatusBar(QStatusBar())
        self._refresh_status()
        self._build_menu()

        # Wiring
        self.timeline.period_selected.connect(self._show_period)
        self.timeline.library_selected.connect(self._show_library)
        self.stream.action_requested.connect(self._selection_action)
        self.stream.context_requested.connect(self._stream_menu)
        self._search_mode = "words"
        self.stream.bookmark_selected.connect(self._show_bookmark)
        self.stream.open_requested.connect(self._open_url)
        self.reader.fetch_requested.connect(self._fetch)
        self.reader.favorite_toggled.connect(self._toggle_fav)
        self.reader.quote_requested.connect(self._save_quote)
        self.reader.takeaway_requested.connect(self._save_takeaway)
        self.reader.open_related.connect(self._show_bookmark)
        self.reader.ia_requested.connect(lambda bid: self._save_to_ia([bid]))
        self.reader.archive_requested.connect(self._archive_page)
        self._install_shortcuts()

        self._show_recent()

    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        def sc(keys, fn, ctx=Qt.WindowShortcut, parent=None):
            s = QShortcut(QKeySequence(keys), parent or self)
            s.setContext(ctx)
            s.activated.connect(fn)
            return s

        def focus_search():
            self.search.setFocus(); self.search.selectAll()

        def esc_search():
            if self.search.text():
                self.search.clear()
            self.stream.view.setFocus()

        sc("Ctrl+F", focus_search)
        sc("Ctrl+L", focus_search)
        sc("Escape", esc_search, Qt.WidgetShortcut, self.search)
        sc("Ctrl+O", lambda: self.reader._open())
        sc("Ctrl+D", lambda: self.reader._toggle_fav())
        sc("Ctrl+Shift+Q", lambda: self.reader._quote())
        sc("Ctrl+Shift+T", lambda: self.reader._takeaway())
        sc("F6", lambda: self._cycle_pane(+1))
        sc("Shift+F6", lambda: self._cycle_pane(-1))

    def _cycle_pane(self, step: int) -> None:
        """Move keyboard focus between timeline, list and reader."""
        panes = [self.timeline.tree, self.stream.view, self.reader.body]
        cur = next((i for i, w in enumerate(panes) if w.hasFocus()), -1)
        panes[(cur + step) % len(panes)].setFocus()

    # -- top bar ------------------------------------------------------------ #
    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 0, 0)
        lay.setSpacing(14)
        brand = QLabel(tr("app.title"))
        self.brand = brand
        brand.setObjectName("Brand")
        lay.addWidget(brand)
        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText(tr("search.placeholder"))
        self.search.setToolTip("Search your archive (Ctrl+F). Esc clears.")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._run_search)
        self.search.textChanged.connect(self._maybe_clear_search)
        self.search.setAccessibleName("Search")
        self.search.setAccessibleDescription(
            "Type and press Enter. Search by words, or switch to search by meaning.")
        lay.addWidget(self.search, 1)
        from PySide6.QtWidgets import QComboBox
        self.search_mode = QComboBox()
        self.search_mode.addItem(tr("search.mode_words"), "words")
        self.search_mode.addItem(tr("search.mode_meaning"), "meaning")
        self.search_mode.setAccessibleName("Search mode")
        self.search_mode.setToolTip("Words finds exact terms. Meaning also finds "
                                    "items about the same thing in other words.")
        self.search_mode.currentIndexChanged.connect(
            lambda i: self._set_search_mode(self.search_mode.itemData(i)))
        lay.addWidget(self.search_mode)
        return bar

    # -- data flows --------------------------------------------------------- #
    def _show_recent(self) -> None:
        counts = self.ctx.stats.stats().by_year
        if counts:
            self._show_period(counts[0][0], 0)
        else:
            self.stream.set_bookmarks([], tr("stream.empty_archive"),
                                      empty_hint=tr("stream.nothing_imported"))
            self.reader.show_welcome()

    def _show_period(self, year: int, month: int) -> None:
        import calendar
        total = self.ctx.storage.count_period(year, month)
        heading = f"{calendar.month_name[month]} {year}" if month else f"{year}"
        # lazy: the model pages in as the user scrolls — no row cap
        self.stream.set_period(self.ctx.storage, year, month, heading, count=total)
        self.timeline.mark(year, month)

    def _run_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            self._show_recent()
            return
        if getattr(self, "_search_mode", "words") == "meaning":
            results = [b for b, _ in self.ctx.related.hybrid_search(q, k=200)]
            head = tr("stream.results_meaning", q=q)
        else:
            results = self.ctx.search.search(q, limit=200)
            head = tr("stream.results", q=q)
        self.stream.set_bookmarks(results, head, count=len(results),
                                  empty_hint=tr("stream.no_match"))

    def _maybe_clear_search(self, text: str) -> None:
        if not text.strip():
            self._show_recent()

    def _show_bookmark(self, bid: int) -> None:
        bm = self.ctx.storage.get(bid)
        if bm:
            self.reader.show_bookmark(bm)
            self.reader.set_notes(len(self.ctx.snippets.for_bookmark(bid)),
                                  len(self.ctx.takeaways.for_bookmark(bid)))
            try:
                from .reader_panel import provenance_sentences
                self.reader.set_provenance(
                    provenance_sentences(self.ctx.provenance.for_bookmark(bid)))
            except Exception:
                self.reader.set_provenance([])
            self._populate_related(bid)
            self._populate_videos(bm)

    def _populate_videos(self, bm) -> None:
        def at(sec):
            return f" (from {sec // 60}:{sec % 60:02d})" if sec else ""
        try:
            if bm.kind == "video":
                pages = self.ctx.videos.found_on(bm.id)
                self.reader.set_videos(
                    "Found on" if pages else "",
                    [(p["title"] + at(p["start"]), p["id"]) for p in pages])
            else:
                vids = self.ctx.videos.videos_on(bm.id)
                self.reader.set_videos(
                    f"Video{'s' if len(vids) != 1 else ''} in this page",
                    [(v.title, v.id) for v in vids])
        except Exception:
            self.reader.set_videos("", [])

    def _save_to_ia(self, ids) -> None:
        if not self.ctx.network.is_allowed("archive_submit"):
            QMessageBox.information(
                self, "Internet Archive",
                "Saving to the Internet Archive is off. It publishes the page\u2019s "
                "address to archive.org, so it has its own switch: turn on networking "
                "and \u201cSave pages to the Internet Archive\u201d in Settings.")
            return
        from ..web.archive_org import wait_between
        n = len(ids)
        if n > 1:
            mins = round(n * wait_between(self.ctx.config.settings) / 60)
            if QMessageBox.question(
                    self, "Internet Archive",
                    f"Save {n} pages to the Internet Archive? They are saved one at a "
                    f"time to stay within its limits, about {max(1, mins)} minute(s). "
                    "You can keep working meanwhile.") != QMessageBox.Yes:
                return

        def job(c):
            r = c.archive.save_many_to_internet_archive(ids)
            msg = f"Saved {len(r['saved'])} of {n} to the Internet Archive."
            if r["failed"]:
                msg += " Not saved: " + "; ".join(e for _, e in r["failed"][:3])
            return msg
        self._run_task(job, "Saving to the Internet Archive\u2026", "Internet Archive")

    def _export_warc(self, ids=None) -> None:
        from ..export.warc import write_warc
        path, _ = QFileDialog.getSaveFileName(
            self, "Export offline copies", "chronos.warc.gz", "Web archive (*.warc.gz)")
        if path:
            n = write_warc(self.ctx, path, ids)
            self.statusBar().showMessage(
                f"{n} offline cop{'y' if n == 1 else 'ies'} written to {path}"
                if n else "None of these have an offline copy yet (Save offline copy "
                          "first).", 8000)

    # -- citations out ----------------------------------------------------- #
    def _send_to_zotero(self, ids) -> None:
        from ..cite.zotero import send_to_zotero
        n = len(ids)

        def job(c):
            sent = send_to_zotero(c, ids)
            return (f"Sent {sent} item{'s' if sent != 1 else ''} to Zotero, into the "
                    "library or collection selected there, with your quotes and "
                    "takeaways as notes.")
        self._run_task(job, f"Sending {n} item{'s' if n != 1 else ''} to Zotero\u2026",
                       "Zotero")

    def _send_to_reading(self, ids) -> None:
        from ..cite.reading import DEFAULT_FOLDER, write_reading_folder
        folder = QFileDialog.getExistingDirectory(
            self, "Nawishtar Reading folder", str(DEFAULT_FOLDER
                                                  if DEFAULT_FOLDER.parent.exists()
                                                  else DEFAULT_FOLDER.parent.parent))
        if not folder:
            return
        r = write_reading_folder(self.ctx, folder, ids)
        msg = (f"{r['written']} snapshot{'s' if r['written'] != 1 else ''} in {folder}. "
               "Nawishtar lists them under Insert, From your library, Reading "
               "(add this folder there if it isn\u2019t inside \u201cNawishtar Reading\u201d).")
        if r["skipped"]:
            msg += (f"\n\n{len(r['skipped'])} skipped: nothing to read yet \u2014 save "
                    "an offline copy first.")
        QMessageBox.information(self, "Nawishtar", msg)

    def _send_to_epub(self, ids) -> None:
        from ..cite.epub import write_epub
        path, _ = QFileDialog.getSaveFileName(
            self, "Reading book for Khwānōk", "chronos-reading.epub", "EPUB (*.epub)")
        if not path:
            return
        try:
            r = write_epub(self.ctx, path, ids)
        except ValueError as e:
            QMessageBox.information(self, "Reading book", str(e)); return
        msg = (f"{r['chapters']} chapter{'s' if r['chapters'] != 1 else ''} in {path}. "
               "Open it in Khwānōk or any e-reader.")
        if r["skipped"]:
            msg += (f"\n\n{len(r['skipped'])} skipped: nothing to read yet \u2014 save "
                    "an offline copy first.")
        QMessageBox.information(self, "Reading book", msg)

    def _find_videos(self) -> None:
        self._run_task(
            lambda c: (lambda r: f"Looked through your offline copies: {r['pages']:,} "
                       f"page(s) contain videos, {r['new_videos']:,} new video(s) "
                       "in your archive.")(c.videos.scan_saved_pages()),
            "Looking for videos in saved pages\u2026", "Videos")

    def _send_to_ytman(self, ids=None) -> None:
        refs = self.ctx.videos.refs(ids)
        if not refs:
            QMessageBox.information(
                self, "Send to ytman",
                "No videos found. Videos come from YouTube or Vimeo links you saved, "
                "and from videos inside pages you keep offline copies of "
                "(Tools, Find videos in saved pages).")
            return
        default = str(self.ctx.config.outbox_dir / "chronos-videos-for-ytman.json")
        path, _ = QFileDialog.getSaveFileName(self, "Send to ytman", default,
                                              "ytman handoff (*.json)")
        if path:
            n = self.ctx.videos.write_ytman_handoff(path, ids)
            self.statusBar().showMessage(
                f"{n} video(s) written for ytman to {path}. Import it in ytman.", 8000)

    def _populate_related(self, bid: int) -> None:
        try:
            hits = self.ctx.related.related(bid, k=4)
            self.reader.set_related([(b.title or b.url, b.id) for b, _ in hits])
        except Exception:
            self.reader.set_related([])

    def _save_quote(self, bid: int, text: str) -> None:
        if not text.strip():
            self.statusBar().showMessage(
                "Select text in the reader first, then press Quote.", 5000)
            return
        self.ctx.snippets.capture(bid, text)
        self.ctx.provenance.record(bid, "manual_capture", "reader")
        self._refresh_notes(bid)
        self.statusBar().showMessage("Quote kept.", 4000)

    def _refresh_notes(self, bid: int) -> None:
        self.reader.set_notes(len(self.ctx.snippets.for_bookmark(bid)),
                              len(self.ctx.takeaways.for_bookmark(bid)))

    def _save_takeaway(self, bid: int) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Takeaway",
            "The one point you want to remember from this:")
        if not ok or not text.strip():
            return
        self.ctx.takeaways.add(bid, text)
        self._refresh_notes(bid)
        self.statusBar().showMessage("Takeaway kept.", 4000)

    def _archive_page(self, bid: int) -> None:
        try:
            r = self.ctx.archive.archive(bid)
        except Exception as e:
            self.statusBar().showMessage(
                f"Could not archive: {e}. Enable networking in Settings.", 5000)
            return
        self.statusBar().showMessage(
            f"Archived offline ({r.bytes // 1024} KB). Content saved locally.", 5000)
        self._show_bookmark(bid)  # refresh reader with newly-stored content

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _toggle_fav(self, bid: int, value: bool) -> None:
        self.ctx.storage.set_favorite(bid, value)
        self._show_bookmark(bid)
        self.timeline._reload_library()

    def _fetch(self, bid: int) -> None:
        self.statusBar().showMessage("Fetching page content…")
        self._worker = FetchWorker(self.ctx.config.app_dir, bid)
        self._worker.done.connect(self._on_fetched)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _on_fetched(self, bid: int) -> None:
        self.statusBar().showMessage("Content fetched.", 4000)
        self._show_bookmark(bid)

    def _on_fetch_failed(self, bid: int, msg: str) -> None:
        self.statusBar().showMessage(f"Fetch failed: {msg}", 6000)

    def _refresh_status(self) -> None:
        total = self.ctx.bookmarks.count()
        net = (tr("status.online") if self.ctx.network.settings.network_enabled
               else tr("status.offline"))
        self.statusBar().showMessage(
            tr("status.summary_one" if total == 1 else "status.summary", n=total, v=self.ctx.storage.version, net=net))

    def retranslate(self) -> None:
        """Re-apply UI strings after a language change (no restart)."""
        self.brand.setText(tr("app.title"))
        self.search.setPlaceholderText(tr("search.placeholder"))
        self.search_mode.setItemText(0, tr("search.mode_words"))
        self.search_mode.setItemText(1, tr("search.mode_meaning"))
        for key, menu in self._menus.items():
            menu.setTitle(_mn(tr(key)))
        for key, action in self._menu_actions:
            action.setText(_mn(tr(key)))
        self.timeline.retranslate()
        self.reader.retranslate()
        self._refresh_status()
        self.stream.retranslate()

    # -- menu --------------------------------------------------------------- #
    def _build_menu(self) -> None:
        from PySide6.QtGui import QAction, QActionGroup, QKeySequence
        mb = self.menuBar()
        self._menus = {}
        self._menu_actions = []

        def menu(key):
            m = mb.addMenu(_mn(tr(key)))
            self._menus[key] = m
            return m

        def act(m, key, fn, keys=None, checkable=False):
            a = QAction(_mn(tr(key)), self)
            a.triggered.connect(fn)
            if keys:
                a.setShortcut(QKeySequence(keys))
            a.setCheckable(checkable)
            m.addAction(a)
            self._menu_actions.append((key, a))
            return a

        m = menu("menu.file")
        act(m, "action.import", self._open_import, "Ctrl+I")
        act(m, "action.capture_setup", self._open_capture_setup)
        act(m, "action.paste_capture", self._paste_capture, "Ctrl+Shift+V")
        m.addSeparator()
        act(m, "action.export", self._export, "Ctrl+E")
        act(m, "action.export_warc", lambda: self._export_warc(None))
        m.addSeparator()
        act(m, "action.quit", self.close, "Ctrl+Q")

        m = menu("menu.view")
        grp = QActionGroup(self)
        self.act_words = act(m, "action.search_words",
                             lambda: self._set_search_mode("words"), checkable=True)
        self.act_meaning = act(m, "action.search_meaning",
                               lambda: self._set_search_mode("meaning"), checkable=True)
        grp.addAction(self.act_words); grp.addAction(self.act_meaning)
        self.act_words.setChecked(True)
        m.addSeparator()
        act(m, "action.text_larger", lambda: self._step_text(+1), "Ctrl+=")
        act(m, "action.text_smaller", lambda: self._step_text(-1), "Ctrl+-")
        act(m, "action.text_default", lambda: self._step_text(0), "Ctrl+0")

        m = menu("menu.items")
        act(m, "action.select_all", lambda: (self.stream.view.setFocus(),
                                             self.stream.view.selectAll()), "Ctrl+A")
        m.addSeparator()
        act(m, "action.ask_ai", lambda: self._selection_action("ask_ai"), "Ctrl+Shift+A")
        act(m, "action.copy_ai", lambda: self._selection_action("copy_ai"), "Ctrl+Shift+C")
        act(m, "action.save_ai", lambda: self._selection_action("save_ai"))
        m.addSeparator()
        act(m, "action.fav_selected", lambda: self._selection_action("favorite"))
        act(m, "action.tag_selected", lambda: self._selection_action("tag"))
        act(m, "action.export_selected", lambda: self._selection_action("export"))
        send = m.addMenu(_mn(tr("menu.send_to")))
        self._menus["menu.send_to"] = send
        act(send, "action.send_zotero", lambda: self._selection_action("zotero"))
        act(send, "action.send_reading", lambda: self._selection_action("reading"))
        act(send, "action.send_epub", lambda: self._selection_action("epub"))
        act(send, "action.send_ytman", lambda: self._selection_action("ytman"))
        act(m, "action.save_ia", lambda: self._selection_action("ia"))
        act(m, "action.warc_selected", lambda: self._selection_action("warc"))
        m.addSeparator()
        act(m, "action.remove_selected", lambda: self._selection_action("remove"))
        self._items_menu = m

        m = menu("menu.feeds")
        act(m, "action.add_feed", self._add_feed)
        act(m, "action.refresh_feeds", self._refresh_feeds)

        m = menu("menu.tools")
        act(m, "action.quotes", self._open_quotes)
        act(m, "action.find_duplicates", self._find_duplicates)
        act(m, "action.check_links", self._check_links)
        act(m, "action.autotag", self._autotag_all)
        act(m, "action.find_videos", self._find_videos)
        act(m, "action.send_ytman_all", lambda: self._send_to_ytman(None))
        act(m, "action.reindex", self._reindex_related)
        m.addSeparator()
        act(m, "action.settings", self._open_settings, "Ctrl+,")

        m = menu("menu.help")
        act(m, "action.shortcuts", self._show_shortcuts, "F1")
        act(m, "action.open_data_folder", self._open_data_folder)
        act(m, "action.about", self._show_about)

    # -- import / capture / export ----------------------------------------- #
    # -- drop anything onto the window ------------------------------------- #
    @staticmethod
    def _dropped_paths(mime):
        if not mime.hasUrls():
            return []
        from pathlib import Path
        return [str(Path(u.toLocalFile())) for u in mime.urls()        # C:\… on Windows
                if u.isLocalFile() and u.toLocalFile()]

    def dragEnterEvent(self, e) -> None:
        if self._dropped_paths(e.mimeData()):
            e.acceptProposedAction()
            self.statusBar().showMessage("Drop to bring it into your archive", 3000)

    def dragMoveEvent(self, e) -> None:
        if self._dropped_paths(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = self._dropped_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.import_paths(paths)

    def import_paths(self, paths) -> None:
        """Bring in any files, folders or archives (also used by drag and drop)."""
        n = len(paths)
        self._run_task(lambda c, ps=list(paths): c.universal.import_paths(ps).text(),
                       f"Reading {n} item{'s' if n != 1 else ''} you dropped\u2026",
                       "Brought in")

    def _open_import(self) -> None:
        from .import_dialog import ImportDialog
        dlg = ImportDialog(self.ctx, self)
        dlg.imported.connect(self._reload_views)
        dlg.exec()

    def _open_capture_setup(self) -> None:
        from .capture_dialog import CaptureDialog
        CaptureDialog(self).exec()

    def _export(self, bookmarks=None) -> None:
        from PySide6.QtWidgets import QInputDialog
        choices = [
            ("Citations: CSL-JSON (Zotero, Nawishtar)", "csl"),
            ("Citations: BibTeX", "bibtex"), ("Citations: RIS", "ris"),
            ("Bookmarks: HTML (any browser can import)", "html"),
            ("Everything: JSON", "json"), ("Spreadsheet: CSV", "csv"),
            ("Feeds: OPML", "opml"),
            ("Quotes: Web Annotation JSON", "annotations"),
            ("Quotes: Markdown", "quotes-md"),
        ]
        what = (f"Export {len(bookmarks)} selected item"
                f"{'s' if len(bookmarks) != 1 else ''} as:" if bookmarks is not None
                else "What to export:")
        if bookmarks is not None:      # feeds and quotes aren't per-item formats
            choices = [c for c in choices if c[1] in
                       ("csl", "bibtex", "ris", "html", "json", "csv")]
        label, ok = QInputDialog.getItem(self, "Export", what,
                                         [c[0] for c in choices], 0, False)
        if not ok:
            return
        fmt = dict(choices)[label]
        suffix = self.ctx.export.default_suffix(fmt)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", f"chronos-{fmt}{suffix}", f"*{suffix}")
        if not path:
            return
        try:
            self.ctx.export.export_to(fmt, path, bookmarks)
            self.statusBar().showMessage(f"Exported to {path}", 6000)
        except Exception as e:
            QMessageBox.warning(self, "Export", f"Couldn\u2019t export. {e}")

    # -- selection: AI and bulk actions ------------------------------------ #
    def _stream_menu(self, global_pos) -> None:
        from PySide6.QtWidgets import QMenu
        n = len(self.stream.selected_ids())
        if not n:
            return
        m = QMenu(self)
        for label, name in (
                (f"Ask AI about {n} item{'s' if n != 1 else ''}\u2026", "ask_ai"),
                ("Copy for AI", "copy_ai"), ("Save for AI\u2026", "save_ai"), None,
                ("Add to favourites", "favorite"), ("Add a tag\u2026", "tag"),
                ("Export these\u2026", "export"), "send",
                ("Save to the Internet Archive", "ia"),
                ("Export offline copies (WARC)\u2026", "warc"), None,
                ("Remove from archive\u2026", "remove")):
            if label is None:
                m.addSeparator(); continue
            if label == "send":
                sub = m.addMenu(tr("menu.send_to"))
                for key, nm in (("action.send_zotero", "zotero"),
                                ("action.send_reading", "reading"),
                                ("action.send_epub", "epub"),
                                ("action.send_ytman", "ytman")):
                    sub.addAction(tr(key)).triggered.connect(
                        lambda _=False, n=nm: self._selection_action(n))
                continue
            a = m.addAction(label[0] if isinstance(label, tuple) else label)
            name = label[1]
            a.triggered.connect(lambda _=False, nm=name: self._selection_action(nm))
        m.exec(global_pos)

    def _selection_action(self, name: str) -> None:
        ids = self.stream.selected_ids()
        if name == "clear":
            self.stream.clear_selection(); return
        if not ids:
            self.statusBar().showMessage(
                "Select one or more items in the list first (Ctrl or Shift to add).", 5000)
            return
        n = len(ids)
        noun = f"{n} item{'s' if n != 1 else ''}"
        if name == "ask_ai":
            from .ai_dialog import AskAIDialog
            dlg = AskAIDialog(self.ctx, ids, self)
            dlg.takeaways_saved.connect(lambda _n: self._refresh_notes(
                self.reader._bm.id) if self.reader._bm else None)
            dlg.open_item.connect(self._show_bookmark)
            dlg.setModal(False)            # read cited items beside the answer
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.show()
        elif name in ("copy_ai", "save_ai"):
            from ..ai.pack import build_pack
            pack = build_pack(self.ctx, ids)
            if name == "copy_ai":
                from PySide6.QtGui import QGuiApplication
                QGuiApplication.clipboard().setText(pack.markdown)
                self.statusBar().showMessage(
                    f"Copied {noun} for AI ({len(pack.markdown):,} characters). Paste "
                    "into any AI chat.", 6000)
            else:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save for AI", "chronos-for-ai.md", "Markdown (*.md)")
                if path:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(pack.markdown)
                    self.statusBar().showMessage(f"Saved {noun} to {path}", 6000)
        elif name == "favorite":
            for i in ids:
                self.ctx.storage.set_favorite(i, True)
            self.timeline._reload_library()
            self.stream.view.viewport().update()
            self.statusBar().showMessage(f"Added {noun} to favourites.", 5000)
        elif name == "tag":
            tag, ok = QInputDialog.getText(self, "Tag", f"Tag for {noun}:")
            tag = tag.strip().lower()
            if ok and tag:
                for i in ids:
                    cur = self.ctx.storage.get(i).tags or []
                    self.ctx.storage.set_tags(i, sorted(set(cur) | {tag}))
                self.statusBar().showMessage(f"Tagged {noun} #{tag}.", 5000)
        elif name == "ia":
            self._save_to_ia(ids)
        elif name == "warc":
            self._export_warc(ids)
        elif name == "ytman":
            self._send_to_ytman(ids)
        elif name == "zotero":
            self._send_to_zotero(ids)
        elif name == "reading":
            self._send_to_reading(ids)
        elif name == "epub":
            self._send_to_epub(ids)
        elif name == "export":
            self._export([b for b in (self.ctx.storage.get(i) for i in ids) if b])
        elif name == "remove":
            ans = QMessageBox.question(
                self, "Remove", f"Remove {noun} from your archive? Their quotes, "
                "takeaways and offline copies are removed too. This can\u2019t be undone.")
            if ans == QMessageBox.Yes:
                r = self.ctx.removal.remove_many(ids)
                self._reload_views()
                self.statusBar().showMessage(f"Removed {r.removed} item(s).", 6000)

    # -- tools -------------------------------------------------------------- #
    def _run_task(self, fn, busy: str, done_title: str) -> None:
        """Run fn(ctx)->str on a worker thread with its own connection."""
        from .workers import TaskWorker
        self.statusBar().showMessage(busy)
        w = TaskWorker(self.ctx.config.app_dir, fn, self)

        def ok(msg):
            self._refresh_status()
            self._reload_views()
            QMessageBox.information(self, done_title, msg)

        def bad(msg):
            self._refresh_status()
            QMessageBox.warning(self, done_title, msg)

        w.done.connect(ok); w.failed.connect(bad)
        self._tasks = getattr(self, "_tasks", []) + [w]
        w.start()

    def _find_duplicates(self) -> None:
        groups = self.ctx.curation.find_duplicate_groups()
        extra = sum(len(g) - 1 for g in groups)
        if not groups:
            QMessageBox.information(self, "Duplicates", "No duplicates found.")
            return
        ans = QMessageBox.question(
            self, "Duplicates",
            f"{extra} extra cop{'y' if extra == 1 else 'ies'} of {len(groups)} "
            f"item{'s' if len(groups) != 1 else ''} found (the same page saved "
            "with small URL differences).\n\nMerge them? Favourites, notes, "
            "tags, quotes and takeaways are kept on the item that stays.")
        if ans == QMessageBox.Yes:
            r = self.ctx.curation.merge_all()
            self._reload_views()
            self.statusBar().showMessage(f"Merged {r.removed} duplicate(s).", 6000)

    def _check_links(self) -> None:
        if not self.ctx.network.is_allowed("link_check"):
            QMessageBox.information(
                self, "Check links",
                "Link checking is off. Turn on networking and \u201cCheck for dead "
                "links\u201d in Settings (Ctrl+,), then try again.")
            return
        wb = self.ctx.network.is_allowed("wayback")
        self._run_task(
            lambda c: (lambda r: f"Checked {r.checked:,} links. {r.dead:,} no longer "
                       f"load" + (f"; {r.archived:,} have an archived copy." if wb
                                  else "."))(c.links.check_all(use_wayback=wb)),
            "Checking links\u2026", "Check links")

    def _autotag_all(self) -> None:
        self._run_task(lambda c: f"Tagged {c.tagging.auto_tag_all():,} items.",
                       "Tagging\u2026", "Tags")

    # -- view --------------------------------------------------------------- #
    def _set_search_mode(self, mode: str) -> None:
        self._search_mode = mode
        if hasattr(self, "search_mode"):
            self.search_mode.setCurrentIndex(0 if mode == "words" else 1)
        if hasattr(self, "act_words"):
            (self.act_words if mode == "words" else self.act_meaning).setChecked(True)
        if self.search.text().strip():
            self._run_search()

    def _step_text(self, step: int) -> None:
        order = ["small", "default", "large", "larger"]
        cur = getattr(self.ctx.config.settings, "text_size", "default")
        i = order.index(cur) if cur in order else 1
        new = "default" if step == 0 else order[max(0, min(len(order) - 1, i + step))]
        if new == cur:
            return
        from dataclasses import replace
        self.apply_settings(replace(self.ctx.config.settings, text_size=new))

    def _show_library(self, facet: str, value: str) -> None:
        from .reader_panel import _src
        from .timeline_panel import _KIND_PLURAL
        if facet == "favorites":
            items, head = self.ctx.storage.favorites(), tr("library.favorites")
        elif facet == "kind":
            items = self.ctx.resources.by_kind(value, 1000)
            head = _KIND_PLURAL.get(value, value)
        else:
            items = self.ctx.provenance.by_source(value, 1000)
            head = tr("library.source", name=_src(value))
        self.stream.set_bookmarks(items, head, empty_hint=tr("library.empty"))

    # -- help --------------------------------------------------------------- #
    def _show_shortcuts(self) -> None:
        rows = [("Ctrl+F", "Search your archive"), ("Esc", "Clear the search"),
                ("\u2191 \u2193", "Move through the list and open items"),
                ("Ctrl+O", "Open the original page"), ("Ctrl+D", "Favourite"),
                ("Ctrl+Shift+Q", "Keep selected text as a quote"),
                ("Ctrl+Shift+T", "Write a takeaway"), ("Ctrl+I", "Import"),
                ("Ctrl+Shift+V", "Paste a capture"), ("Ctrl+E", "Export"),
                ("Ctrl+=  Ctrl+-  Ctrl+0", "Text size"), ("Ctrl+,", "Settings"),
                ("F6", "Move between timeline, list and reader"), ("F1", "This list")]
        html = "<table cellpadding='4'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        box = QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    @property
    def _portable(self) -> bool:
        from pathlib import Path
        from ..core.config import program_dir
        pd = program_dir()
        try:
            return pd is not None and Path(self.ctx.config.app_dir).resolve().is_relative_to(pd)
        except (OSError, ValueError):
            return False

    def _open_data_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        d = self.ctx.config.app_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
        self.statusBar().showMessage(f"Your archive is in {d}", 8000)

    def _show_about(self) -> None:
        from .. import __codename__
        QMessageBox.about(
            self, "About Chronos",
            f"<p><b>Chronos {__version__}</b> \u2014 {__codename__}</p>"
            "<p>A local archive of what you read, save and share on the web. "
            "Nothing leaves this computer unless you turn networking on.</p>"
            f"<p>Your archive is stored in:<br>{self.ctx.config.app_dir}"
            + ("<br>(portable: kept with the program)" if self._portable else "")
            + "</p>")

    def _paste_capture(self) -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox
        text = QApplication.clipboard().text().strip()
        try:
            r = self.ctx.capture.ingest_json(text)
        except Exception as e:
            QMessageBox.warning(self, "Paste capture",
                                f"Clipboard isn't a valid capture JSON.\n{e}")
            return
        self._reload_views()
        QMessageBox.information(
            self, "Capture",
            f"Captured as {r.kind}" + (" with a quote." if r.quoted else "."))

    def _reindex_related(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        n = self.ctx.related.reindex()
        if self.reader._bm is not None:
            self._populate_related(self.reader._bm.id)
        QMessageBox.information(self, "Related", f"Indexed {n} resource(s).")

    def _ingest_inbox(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        folder = QFileDialog.getExistingDirectory(self, "Choose capture folder")
        if not folder:
            return
        n = self.ctx.capture.ingest_inbox(folder)
        self._reload_views()
        QMessageBox.information(self, "Inbox", f"Ingested {n} capture(s).")

    def _reload_views(self) -> None:
        self.timeline.reload()
        self._show_recent()
        self._refresh_status()

    def _import_file(self, kind: str) -> None:
        filt = {"bookmarks": "Bookmark DB / JSON (*.sqlite *.db Bookmarks *)",
                "html": "HTML (*.html *.htm)",
                "history": "History DB (*.sqlite *.db History *)"}[kind]
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", "", filt)
        if not path:
            return
        try:
            if kind == "html":
                r = self.ctx.bookmarks.import_html(path)
            elif kind == "history":
                imp = "firefox history" if str(path).endswith(("sqlite", "db")) \
                      else "chrome history"
                r = self.ctx.bookmarks.import_from(imp, path)
            else:
                imp = "firefox" if str(path).endswith(("sqlite", "db")) else "chrome"
                r = self.ctx.bookmarks.import_from(imp, path)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        QMessageBox.information(self, "Import",
                                f"{r.browser}: {r.inserted} new of {r.found}.")
        self._reload_views()

    def _add_feed(self) -> None:
        url, ok = QInputDialog.getText(self, "Add feed", "Feed URL:")
        if not (ok and url.strip()):
            return
        try:
            r = self.ctx.feeds.subscribe(url.strip())
        except Exception as e:
            QMessageBox.warning(
                self, "Feed",
                f"{e}\n\nEnable networking + feeds in Settings to fetch feeds.")
            return
        QMessageBox.information(
            self, "Feed", f"'{r.title}': {r.new} new of {r.found} entries.")
        self._reload_views()

    def _refresh_feeds(self) -> None:
        results = self.ctx.feeds.refresh_all()
        total_new = sum(r.new for r in results)
        QMessageBox.information(
            self, "Feeds",
            f"Refreshed {len(results)} feed(s): {total_new} new entries."
            if results else "No feeds, or networking is off.")
        self._reload_views()

    def _open_quotes(self) -> None:
        from .quotes_dialog import QuotesDialog
        QuotesDialog(self.ctx.provider().list_quotes(), self).exec()

    def _open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.ctx.network.settings, self)
        if dlg.exec():
            new = dlg.result_settings()
            self.apply_settings(new)

    def apply_settings(self, new) -> None:
        """Persist settings and update the live policy/UI (headless-testable)."""
        old_theme = self.ctx.network.settings.theme
        old_size = getattr(self.ctx.network.settings, "text_size", "default")
        old_lang = getattr(self.ctx.network.settings, "language", "en")
        self.ctx.config.save_settings(new)
        self.ctx.config._settings = new
        self.ctx.network.settings = new
        self.reader.set_network_allowed(self.ctx.network.is_allowed("page_fetch"))
        self._refresh_status()
        if new.theme != old_theme or getattr(new, "text_size", "default") != old_size:
            self._apply_theme(new.theme)
        if getattr(new, "language", "en") != old_lang:
            self._apply_language(new.language)

    def _apply_language(self, lang: str) -> None:
        from . import i18n
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        i18n.set_locale(lang)
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(
                Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.retranslate()

    def _apply_theme(self, theme_name: str) -> None:
        from .theme.tokens import THEMES, apply_palette, build_qss
        from PySide6.QtWidgets import QApplication
        from .theme.tokens import with_scale
        tokens = with_scale(THEMES.get(theme_name, THEMES["dusk"]),
                            getattr(self.ctx.config.settings, "text_size", "default"))
        self.tokens = tokens
        app = QApplication.instance()
        if app is not None:
            apply_palette(app, tokens)
            app.setStyleSheet(build_qss(tokens))
        self.stream.set_tokens(tokens)
        self.reader.set_tokens(tokens)
