"""Self-test: can this copy of Chronos actually run?

Used by the Windows build (`Chronos.exe --selftest report.txt`,
`chronos-cli.exe selftest`) and useful on any computer. It works in a
throw-away folder — your own archive is never opened — and checks the things a
packaged program most often loses: its translations, the browser-extension
files, the picture formats the theme draws with, the database and search, and
every export.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, List, Optional, Tuple

PAGE = ("<html><head><meta name='author' content='Ada Lindqvist'>"
        "<meta property='og:site_name' content='Field Notes'></head><body><article>"
        "<h1>Brahui verbs</h1><p>Brahui is a Dravidian language.</p>"
        "<p>براہوئی زبان میں ڈ اور ڑ ہیں۔</p></article></body></html>")


def _checks(work: Path, gui: bool) -> Tuple[List[Tuple[str, Callable[[], str]]], dict]:
    state = {}

    def version():
        from . import __codename__, __version__
        import bridgespec
        return f"Chronos {__version__} “{__codename__}”, bridgespec {bridgespec.CONTRACT_VERSION}"

    def database():
        from .core.context import ApplicationContext
        from .core.models import Bookmark
        ctx = ApplicationContext.for_dir(work / "archive")
        state["ctx"] = ctx
        bid, _ = ctx.storage.upsert_bookmark(Bookmark(
            url="https://example.org/brahui", title="Brahui verbs",
            date_added=1700000000, browser="Self-test"))
        ctx.archive.archive_from_html(bid, PAGE, "https://example.org/brahui")
        ctx.snippets.capture(bid, "a Dravidian language")
        state["id"] = bid
        return f"database version {ctx.storage.version}"

    def search():
        ctx = state["ctx"]
        hits = ctx.search.search("Dravidian")
        if not hits:
            raise AssertionError("full-text search found nothing")
        return f"{len(hits)} result(s)"

    def exports():
        ctx, bid = state["ctx"], state["id"]
        from bridgespec import validate_csl_item
        from .cite.epub import write_epub
        from .cite.reading import write_reading_folder
        from .export.exporters import to_bibtex
        from .export.warc import write_warc
        from .interop import bookmark_to_csl
        bm = ctx.storage.get(bid)
        problems = validate_csl_item(bookmark_to_csl(bm))
        if problems:
            raise AssertionError(f"CSL: {problems}")
        assert "@online{" in to_bibtex([bm])
        assert write_epub(ctx, work / "t.epub", [bid])["chapters"] == 1
        assert write_reading_folder(ctx, work / "reading", [bid])["written"] == 1
        assert write_warc(ctx, work / "t.warc.gz", [bid]) == 1
        return "CSL, BibTeX, EPUB, Nawishtar snapshot, WARC"

    def translations():
        from .gui import i18n
        locs = i18n.available_locales()
        if not {"en", "ar", "brh"} <= set(locs):
            raise AssertionError(f"translation files missing: found {locs}")
        return ", ".join(locs)

    def extension_files():
        from .extension.install import unpack_to
        files = sorted(p.name for p in unpack_to(work / "ext").iterdir())
        if "manifest.json" not in files:
            raise AssertionError(f"browser extension incomplete: {files}")
        return f"{len(files)} files"

    def feeds():
        try:
            import feedparser
        except ImportError:
            if getattr(sys, "frozen", False):          # the packaged app must carry it
                raise AssertionError("feed reader (feedparser) not bundled")
            return "feedparser not installed (optional when run from source)"
        return f"feedparser {feedparser.__version__}"

    checks = [("version", version), ("feeds", feeds), ("database", database), ("search", search),
              ("exports", exports), ("translations", translations),
              ("browser extension", extension_files)]

    if gui:
        def qt():
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QImageReader
            app = QApplication.instance() or QApplication([])
            state["app"] = app
            fmts = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
            if "svg" not in fmts:
                raise AssertionError("SVG pictures can't be drawn (Qt svg plugin missing)")
            return f"Qt {__import__('PySide6').__version__}, platform {app.platformName()}"

        def window():
            from .gui.app import app_icon
            from .gui.main_window import MainWindow
            from .gui.theme.tokens import THEMES, apply_palette, build_qss
            app = state["app"]
            apply_palette(app, THEMES["dusk"]); app.setStyleSheet(build_qss(THEMES["dusk"]))
            if app_icon().isNull():
                raise AssertionError("app icon missing")
            w = MainWindow(state["ctx"])
            w.show(); app.processEvents()
            w._show_bookmark(state["id"]); app.processEvents()
            title = w.reader.title.text() if hasattr(w.reader, "title") else ""
            w.close(); app.processEvents()
            return f"main window opened{(' — ' + title) if title else ''}"

        checks += [("Qt", qt), ("window", window)]
    return checks, state


def run_selftest(gui: bool = False, report: Optional[str] = None) -> int:
    import shutil
    lines, ok = [], True
    d = tempfile.mkdtemp(prefix="chronos_selftest_")
    try:
        checks, state = _checks(Path(d), gui)
        for name, fn in checks:
            try:
                lines.append(f"PASS  {name}: {fn()}")
            except Exception as e:                       # report, keep going
                ok = False
                lines.append(f"FAIL  {name}: {e}")
                lines += ["      " + ln for ln in traceback.format_exc().splitlines()[-6:]]
        if "ctx" in state:
            state["ctx"].close()
    finally:
        shutil.rmtree(d, ignore_errors=True)            # Windows keeps open files locked
    lines.append("RESULT: " + ("all checks passed" if ok else "some checks FAILED"))
    text = "\n".join(lines) + "\n"
    if report:
        Path(report).write_text(text, encoding="utf-8")
    if sys.stdout is not None:                          # None in the windowed .exe
        try:
            sys.stdout.write(text)
        except (OSError, UnicodeEncodeError):
            sys.stdout.write(text.encode("ascii", "replace").decode())
    return 0 if ok else 1
