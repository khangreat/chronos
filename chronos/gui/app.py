"""GUI entry point. `run_gui()` builds the QApplication, applies the theme, and
shows the MainWindow on top of a fresh ApplicationContext.
"""

from __future__ import annotations

import sys
from typing import Optional

from ..core.context import ApplicationContext
from .theme.tokens import THEMES, apply_palette, build_qss, with_scale


def build_app(theme: str = "dusk"):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Chronos Archive")
    tokens = THEMES.get(theme, THEMES["dusk"])
    apply_palette(app, tokens)
    app.setStyleSheet(build_qss(tokens))
    return app


def portable_first_run(ask=None) -> Optional[str]:
    """The portable app's first start, when an archive from an earlier Chronos
    exists in ~/.chronos_archive: ask whether to copy it in, keep using it
    where it is, or start empty. Nothing is ever moved or deleted — copying
    leaves the original in place. Returns what was chosen ("copy", "keep",
    "new", or None when there was nothing to ask / the question was closed).

    `ask(legacy_path) -> "copy" | "keep" | "new" | None` is the question;
    by default a dialog."""
    import shutil
    from ..core.config import (legacy_archive_to_offer, portable_dir, portable_marker,
                               portable_choice, record_portable_choice)
    marker = portable_marker()
    if marker is None:
        return None
    legacy = legacy_archive_to_offer(marker)
    try:
        if legacy is None:
            if portable_choice(marker) is None:
                record_portable_choice(marker, "data")
            return None
        answer = (ask or _ask_about_legacy)(legacy)
        if answer is None:               # closed: the earlier archive is used; asked again next time
            return None
        if answer == "copy":
            shutil.copytree(legacy, portable_dir(marker), dirs_exist_ok=True)
            record_portable_choice(marker, "data")
        elif answer == "keep":
            record_portable_choice(marker, str(legacy))
        else:
            record_portable_choice(marker, "data")
        return answer
    except OSError:
        return None                      # read-only folder: default_app_dir falls back


def _ask_about_legacy(legacy) -> Optional[str]:
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox()
    box.setWindowTitle("Chronos")
    box.setIcon(QMessageBox.Question)
    box.setText("You already have a Chronos archive on this computer.")
    box.setInformativeText(
        f"It is in {legacy}.\n\nThis portable Chronos keeps its archive in the "
        "\u201cdata\u201d folder next to it, so you can carry it on a USB stick or "
        "move the folder. What should it use?")
    copy = box.addButton("Copy it here", QMessageBox.AcceptRole)
    keep = box.addButton("Keep using it where it is", QMessageBox.AcceptRole)
    new = box.addButton("Start a new, empty archive", QMessageBox.AcceptRole)
    later = box.addButton("Decide later", QMessageBox.RejectRole)
    later.setToolTip("Use the archive where it is for now, and ask again next time")
    box.setDefaultButton(copy)
    box.exec()
    return {copy: "copy", keep: "keep", new: "new"}.get(box.clickedButton())


def app_icon():
    from pathlib import Path
    from PySide6.QtGui import QIcon
    p = Path(__file__).parent / "assets" / "chronos.png"
    return QIcon(str(p)) if p.exists() else QIcon()


def run_gui(theme: str = "dusk", ctx: Optional[ApplicationContext] = None) -> int:
    app = build_app(theme)
    app.setWindowIcon(app_icon())
    if ctx is None:
        portable_first_run()
    from .main_window import MainWindow
    from . import i18n
    from PySide6.QtCore import Qt
    own = ctx is None
    ctx = ctx or ApplicationContext()
    st = ctx.config.settings
    theme_name = st.theme if st.theme in THEMES else theme
    tokens = with_scale(THEMES[theme_name], getattr(st, "text_size", "default"))
    apply_palette(app, tokens)
    app.setStyleSheet(build_qss(tokens))
    lang = ctx.config.settings.language
    i18n.set_locale(lang)
    app.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
    win = MainWindow(ctx, tokens)
    win.show()
    try:
        return app.exec()
    finally:
        if own:
            ctx.close()


def main(argv=None) -> int:
    """Entry for the packaged Chronos.exe: `--selftest [report.txt]` checks the
    program can start (used by the build), otherwise opens the window."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--selftest"]:
        from ..selftest import run_selftest
        return run_selftest(gui=True, report=argv[1] if len(argv) > 1 else None)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
