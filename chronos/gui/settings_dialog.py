"""Settings dialog — surfaces the network capability toggles (all off by
default), theme, and extractor preference. `result_settings()` returns a fresh
Settings object; the main window persists it and updates the live policy.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..core.config import Settings
from .i18n import available_locales, tr


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._orig = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.resize(560, 680)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget(); body.setObjectName("BodyWrap")
        v = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        def section(title, note=None, first=False):
            h = QLabel(title); h.setObjectName("GroupTitle")
            h.setContentsMargins(0, 0 if first else 14, 0, 0); v.addWidget(h)
            if note:
                n = QLabel(note); n.setObjectName("ReaderMeta"); n.setWordWrap(True)
                v.addWidget(n)

        section("Network", "Off by default. Nothing reaches the network unless the "
                "master switch and the specific capability are both on.", first=True)

        form = QFormLayout()
        self.master = QCheckBox("Enable networking (master switch)")
        self.master.setChecked(settings.network_enabled)
        self.page = QCheckBox("Fetch page content (reader)")
        self.page.setChecked(settings.allow_page_fetch)
        self.feeds = QCheckBox("Fetch RSS/Atom feeds")
        self.feeds.setChecked(settings.allow_feeds)
        self.link = QCheckBox("Check for dead links")
        self.link.setChecked(settings.allow_link_check)
        self.wb = QCheckBox("Look up Wayback snapshots")
        self.wb.setChecked(settings.allow_wayback)
        self.ia = QCheckBox("Save pages to the Internet Archive")
        self.ia.setToolTip("Publishes the address of each page you choose to save "
                           "to archive.org, where anyone can view the snapshot.")
        self.ia.setChecked(getattr(settings, "allow_archive_submit", False))
        self.ia_keys = QLineEdit(getattr(settings, "ia_keys", ""))
        self.ia_keys.setEchoMode(QLineEdit.Password)
        self.ia_keys.setPlaceholderText("Optional keys: access:secret (raises the daily limit)")
        self.ia_keys.setAccessibleName("Internet Archive keys")
        self.private = QCheckBox("Also fetch addresses on my own network (home server, NAS)")
        self.private.setToolTip("Off: pages on your computer or local network (localhost, "
                                "192.168.\u2026, router pages) are never fetched, and no "
                                "web page can redirect Chronos there.")
        self.private.setChecked(getattr(settings, "allow_private_addresses", False))
        for w in (self.master, self.page, self.feeds, self.link, self.wb, self.ia,
                  self.ia_keys, self.private):
            form.addRow(w)
        v.addLayout(form)

        section("Appearance and language")

        form2 = QFormLayout()
        from .theme.tokens import THEME_LABELS, TEXT_SIZES
        names = {"en": "English", "ar": "Arabic (\u0627\u0644\u0639\u0631\u0628\u064a\u0629)",
                 "brh": "Brahui"}

        def combo(pairs, current, acc):
            c = QComboBox()
            for label, key in pairs:
                c.addItem(label, key)
            i = c.findData(current)
            c.setCurrentIndex(i if i >= 0 else 0)
            c.setAccessibleName(acc)
            return c

        self.language = combo([(names.get(l, l), l) for l in available_locales()],
                              getattr(settings, "language", "en"), "Language")
        form2.addRow(tr("settings.language"), self.language)
        self.theme = combo([(v, k) for k, v in THEME_LABELS.items()],
                           settings.theme if settings.theme in THEME_LABELS else "dusk",
                           "Theme")
        form2.addRow("Theme", self.theme)
        self.text_size = combo(
            [("Small", "small"), ("Default", "default"), ("Large", "large"),
             ("Larger", "larger")],
            getattr(settings, "text_size", "default"), "Text size")
        form2.addRow("Text size", self.text_size)
        from ..web.extract import available_extractors
        have = available_extractors()
        best = "Trafilatura" if "trafilatura" in have else (
            "Readability" if "readability" in have else "built in")
        self.extractor = combo(
            [(f"Best available ({best})", "auto"), ("Built in", "builtin")]
            + [(n.capitalize(), n) for n in have if n != "builtin"],
            settings.prefer_extractor, "Page text extractor")
        self.extractor.setToolTip("How Chronos finds the article in a saved page. "
                                  "Trafilatura leaves out menus, ads and footers.")
        form2.addRow("Page text extractor", self.extractor)
        v.addLayout(form2)

        # -- AI -------------------------------------------------------------- #
        section("AI", "Ask a model about items you select. A model on this computer "
                "(Ollama, LM Studio, llama.cpp) keeps everything here. Copy for AI "
                "works without any of this.")
        form3 = QFormLayout()
        self.ai_on = QCheckBox("Use AI")
        self.ai_on.setChecked(getattr(settings, "allow_ai", False))
        form3.addRow(self.ai_on)
        self.ai_preset = QComboBox()
        self.ai_preset.setAccessibleName("AI server")
        for label, url in (("Ollama on this computer", "http://localhost:11434/v1"),
                           ("LM Studio on this computer", "http://localhost:1234/v1"),
                           ("llama.cpp server on this computer", "http://localhost:8080/v1"),
                           ("Other address", "")):
            self.ai_preset.addItem(label, url)
        self.ai_endpoint = QLineEdit(getattr(settings, "ai_endpoint", ""))
        self.ai_endpoint.setAccessibleName("AI address")
        i = self.ai_preset.findData(self.ai_endpoint.text().rstrip("/"))
        self.ai_preset.setCurrentIndex(i if i >= 0 else self.ai_preset.count() - 1)
        self.ai_preset.currentIndexChanged.connect(
            lambda _i: self.ai_endpoint.setText(self.ai_preset.currentData())
            if self.ai_preset.currentData() else None)
        form3.addRow("Server", self.ai_preset)
        form3.addRow("Address", self.ai_endpoint)
        mrow = QHBoxLayout()
        self.ai_model = QComboBox(); self.ai_model.setEditable(True)
        self.ai_model.setAccessibleName("Model")
        self.ai_model.setCurrentText(getattr(settings, "ai_model", ""))
        self.ai_model.lineEdit().setPlaceholderText("Leave empty to use the first available")
        self.find_models = QPushButton("Find models")
        self.find_models.clicked.connect(self._find_models)
        mrow.addWidget(self.ai_model, 1); mrow.addWidget(self.find_models)
        form3.addRow("Model", mrow)
        self.ai_key = QLineEdit(getattr(settings, "ai_api_key", ""))
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setPlaceholderText("Only for services that need one")
        self.ai_key.setAccessibleName("API key")
        form3.addRow("Key", self.ai_key)
        self.ai_remote = QCheckBox("Allow AI services on other computers")
        self.ai_remote.setChecked(getattr(settings, "allow_ai_remote", False))
        form3.addRow(self.ai_remote)
        warn = QLabel("With this on, the items you choose to ask about (their text, "
                      "your quotes and takeaways) are sent to that service. It also "
                      "needs the network master switch. The key is stored in your "
                      "settings file on this computer.")
        warn.setObjectName("ReaderMeta"); warn.setWordWrap(True)
        form3.addRow(warn)
        self.ai_status = QLabel(""); self.ai_status.setObjectName("ReaderMeta")
        self.ai_status.setWordWrap(True)
        form3.addRow(self.ai_status)
        v.addLayout(form3)
        v.addStretch(1)

        self.master.toggled.connect(self._sync_enabled)
        self._sync_enabled(self.master.isChecked())
        self.ai_on.toggled.connect(self._sync_ai)
        self._sync_ai(self.ai_on.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _sync_ai(self, on: bool) -> None:
        for w in (self.ai_preset, self.ai_endpoint, self.ai_model, self.find_models,
                  self.ai_key, self.ai_remote):
            w.setEnabled(on)

    def _find_models(self) -> None:
        from ..ai import client
        from ..net.policy import NetworkPolicy
        st = self.result_settings()
        try:
            models = client.list_models(st, NetworkPolicy(st))
        except Exception as e:
            self.ai_status.setText(str(e))
            return
        cur = self.ai_model.currentText()
        self.ai_model.clear()
        self.ai_model.addItems(models)
        if cur:
            self.ai_model.setCurrentText(cur)
        self.ai_status.setText(f"Found {len(models)} model(s)." if models else
                               "The server answered but has no models loaded.")

    def _sync_enabled(self, on: bool) -> None:
        for w in (self.page, self.feeds, self.link, self.wb, self.ia, self.ia_keys,
                  self.private):
            w.setEnabled(on)

    def result_settings(self) -> Settings:
        # update the existing settings so fields not shown here are kept
        return replace(self._orig,
            network_enabled=self.master.isChecked(),
            allow_page_fetch=self.page.isChecked(),
            allow_feeds=self.feeds.isChecked(),
            allow_link_check=self.link.isChecked(),
            allow_wayback=self.wb.isChecked(),
            theme=self.theme.currentData(),
            prefer_extractor=self.extractor.currentData(),
            language=self.language.currentData(),
            text_size=self.text_size.currentData(),
            allow_archive_submit=self.ia.isChecked(),
            allow_private_addresses=self.private.isChecked(),
            ia_keys=self.ia_keys.text().strip(),
            allow_ai=self.ai_on.isChecked(),
            allow_ai_remote=self.ai_remote.isChecked(),
            ai_endpoint=self.ai_endpoint.text().strip(),
            ai_model=self.ai_model.currentText().strip(),
            ai_api_key=self.ai_key.text().strip(),
        )
