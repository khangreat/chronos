# PyInstaller spec — Chronos portable (one folder, two programs).
#
#   Chronos.exe      the window (no console)
#   chronos-cli.exe  the command line, and the browser extension's helper
#
# Both share one set of libraries. Build from the repository root:
#   pyinstaller packaging/windows/chronos.spec --noconfirm
# The result is dist/Chronos/. The workflow adds portable.txt and zips it.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
WIN = sys.platform.startswith("win")
ICON = str(HERE / "chronos.ico") if WIN else None

datas = collect_data_files("chronos")           # translations, icon, extension files
hidden = (collect_submodules("chronos") + collect_submodules("bridgespec")
          + ["PySide6.QtSvg"])                  # the theme draws arrows/ticks as SVG
# Trafilatura finds the article in a saved page (leaves out menus, ads, footers);
# its helpers carry word lists and settings as data files.
for pkg in ("trafilatura", "justext", "courlan", "htmldate"):
    try:
        datas += collect_data_files(pkg)
        hidden += collect_submodules(pkg)
    except Exception:
        pass
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"]


def analysis(script):
    return Analysis([str(HERE / script)], pathex=[str(HERE.parents[1])],
                    datas=datas, hiddenimports=hidden, excludes=excludes,
                    noarchive=False)


gui_a = analysis("chronos_gui.py")
cli_a = analysis("chronos_cli.py")

gui_exe = EXE(PYZ(gui_a.pure), gui_a.scripts, [], exclude_binaries=True,
              name="Chronos", console=False, icon=ICON, upx=False)
cli_exe = EXE(PYZ(cli_a.pure), cli_a.scripts, [], exclude_binaries=True,
              name="chronos-cli", console=True, icon=ICON, upx=False)

COLLECT(gui_exe, gui_a.binaries, gui_a.datas,
        cli_exe, cli_a.binaries, cli_a.datas,
        name="Chronos", upx=False)
