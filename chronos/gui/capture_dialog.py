"""Browser capture window — set up saving posts and pages from the browser.

Two ways, both local (nothing goes through a server):
  1. The extension: a "Save to Chronos" button that saves straight into the
     archive. Three steps, each a button here.
  2. The bookmarklet: works in any browser with no install; saves a small file
     you bring in with Import, Capture folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..extension import install as inst
from ..services.capture_service import bookmarklet


class CaptureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capture from your browser")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        lay.setSpacing(8)

        def head(t):
            h = QLabel(t); h.setObjectName("GroupTitle")
            h.setContentsMargins(0, 10, 0, 0); lay.addWidget(h)

        def note(t):
            n = QLabel(t); n.setObjectName("ReaderMeta"); n.setWordWrap(True)
            n.setTextInteractionFlags(Qt.TextSelectableByMouse); lay.addWidget(n)
            n.setVisible(bool(t))
            return n

        note("Save a specific post or page while you browse, with its author, "
             "date and your selected text. Everything stays on this computer.")

        # -- extension ----------------------------------------------------- #
        head("Browser extension (one click)")
        note("1.  Copy the extension files to a folder you keep.")
        r1 = QHBoxLayout()
        self.unpack_btn = QPushButton("Copy extension files…")
        self.unpack_btn.clicked.connect(self._unpack)
        r1.addWidget(self.unpack_btn); r1.addStretch(1); lay.addLayout(r1)
        self.unpack_status = note("")

        note("2.  In your browser, open the extensions page, turn on developer "
             "mode, choose “Load unpacked”, and pick that folder. Then copy "
             "the extension ID it shows.")

        note("3.  Paste the ID here and connect it to Chronos.")
        r3 = QHBoxLayout()
        self.browser = QComboBox()
        for label, key in (("Chrome", "chrome"), ("Edge", "edge"),
                           ("Chromium / Brave", "chromium"), ("Firefox", "firefox")):
            self.browser.addItem(label, key)
        self.browser.setAccessibleName("Browser")
        self.ext_id = QLineEdit()
        self.ext_id.setPlaceholderText("Extension ID")
        self.ext_id.setAccessibleName("Extension ID")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._connect)
        r3.addWidget(self.browser); r3.addWidget(self.ext_id, 1)
        r3.addWidget(self.connect_btn); lay.addLayout(r3)
        self.connect_status = note("")

        # -- bookmarklet --------------------------------------------------- #
        head("Bookmarklet (no install)")
        note("Copy it, make a new bookmark in your browser, and paste it as the "
             "address. Clicking it on a post saves a small capture file to your "
             "Downloads; bring those in with Import, Capture folder.")
        r4 = QHBoxLayout()
        self.copy_bm = QPushButton("Copy bookmarklet")
        self.copy_bm.clicked.connect(self._copy_bookmarklet)
        r4.addWidget(self.copy_bm); r4.addStretch(1); lay.addLayout(r4)
        self.bm_status = note("")
        lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Done")
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # -- actions ------------------------------------------------------------ #
    def unpack(self, folder: str) -> Path:
        dest = inst.unpack_to(Path(folder) / "chronos-extension")
        self.unpack_status.setVisible(True)
        self.unpack_status.setText(f"Copied to {dest}")
        return dest

    def _unpack(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Where should the extension live?")
        if folder:
            self.unpack(folder)

    def connect_extension(self, ext_id: str, browser: str, home=None) -> str:
        ext_id = ext_id.strip()
        if not ext_id:
            msg = "Paste the extension ID from your browser’s extensions page first."
            self.connect_status.setVisible(True)
            self.connect_status.setText(msg)
            return msg
        paths = inst.install(ext_id, browser, home=home)
        if paths["needs_registry"]:
            if inst.register_windows(paths["manifest"], browser):
                msg = "Connected. Restart the browser, then use Save to Chronos."
            else:
                cmd = inst.registry_command(paths["manifest"], browser)
                QGuiApplication.clipboard().setText(cmd)
                msg = ("Almost done: Windows didn’t accept the setting. A command "
                       "has been copied; paste it into a Command Prompt once.")
        else:
            msg = "Connected. Restart the browser, then use Save to Chronos."
        self.connect_status.setVisible(True)
        self.connect_status.setText(msg)
        return msg

    def _connect(self) -> None:
        self.connect_extension(self.ext_id.text(), self.browser.currentData())

    def _copy_bookmarklet(self) -> None:
        QGuiApplication.clipboard().setText(bookmarklet())
        self.bm_status.setVisible(True)
        self.bm_status.setText("Copied. Paste it as the address of a new bookmark.")
