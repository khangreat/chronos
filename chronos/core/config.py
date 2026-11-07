"""Configuration and filesystem paths.

Truth boundaries:
  - SQLite (bookmarks.db) is the sole store of entity truth (bookmarks/tags).
  - JSON (settings.json) holds settings only — never entity data.

Nothing here touches the network. Paths are overridable so tests run fully
isolated in a temp dir (never against the real ~/.chronos_archive).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict


LEGACY_DIR_NAME = ".chronos_archive"
PORTABLE_MARKER = "portable.txt"


def home_app_dir() -> Path:
    return Path.home() / LEGACY_DIR_NAME


def program_dir() -> Path | None:
    """The folder holding Chronos.exe when running the packaged app, else None."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def portable_marker(base: Path | None = None) -> Path | None:
    """`portable.txt` beside the program means: keep the data with the program."""
    base = base or program_dir()
    if base is None:
        return None
    m = base / PORTABLE_MARKER
    return m if m.is_file() else None


def portable_choice(marker: Path) -> str | None:
    """The `data=` line in portable.txt (None when no choice is recorded)."""
    try:
        for line in marker.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.lower().startswith("data="):
                return line[5:].strip() or None
    except OSError:
        pass
    return None


def record_portable_choice(marker: Path, data: str) -> None:
    """Write (or replace) the `data=` line, keeping the rest of the file."""
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    lines = [ln for ln in lines if not ln.strip().lower().startswith("data=")]
    lines.append(f"data={data}")
    marker.write_text("\n".join(lines) + "\n", encoding="utf-8")


def portable_dir(marker: Path) -> Path:
    choice = portable_choice(marker) or "data"
    p = Path(choice).expanduser()
    return p if p.is_absolute() else marker.parent / p


def default_app_dir() -> Path:
    """Where your archive lives:
    1. CHRONOS_HOME, if set;
    2. the portable app: `data` beside Chronos.exe, or the folder named by the
       `data=` line in portable.txt (if that folder can be written to);
    3. otherwise `~/.chronos_archive`."""
    env = os.environ.get("CHRONOS_HOME")
    if env:
        return Path(env).expanduser()
    marker = portable_marker()
    if marker is not None:
        if legacy_archive_to_offer(marker) is not None:
            return home_app_dir()        # not chosen yet: never split your archive
        target = portable_dir(marker)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write_test"
            probe.write_text("ok"); probe.unlink()
            return target
        except OSError:
            pass                         # read-only place (e.g. Program Files)
    return home_app_dir()


def legacy_archive_to_offer(marker: Path | None = None) -> Path | None:
    """On the portable app's first run: an archive from an earlier Chronos in
    ~/.chronos_archive that the person may want to bring along (None if
    there's nothing to ask)."""
    if os.environ.get("CHRONOS_HOME"):
        return None
    marker = marker if marker is not None else portable_marker()
    if marker is None or portable_choice(marker) is not None:
        return None
    if (portable_dir(marker) / "bookmarks.db").exists():
        return None
    legacy = home_app_dir()
    return legacy if (legacy / "bookmarks.db").exists() else None


@dataclass
class Settings:
    """User-facing settings. Persisted as JSON, never holds bookmark data."""

    # Network is OFF by default. Every outbound feature checks this gate.
    network_enabled: bool = False
    allow_link_check: bool = False
    allow_wayback: bool = False
    allow_page_fetch: bool = False
    allow_feeds: bool = False
    # Which page-text extractor to use. "auto" = the best this copy has (the
    # Windows build includes Trafilatura); never auto-installed.
    prefer_extractor: str = "auto"  # auto | builtin | trafilatura | readability
    theme: str = "system"
    language: str = "en"  # UI locale (en, ar, brh, …); RTL locales flip layout
    text_size: str = "default"  # small | default | large | larger
    # AI (off by default). A local model (Ollama, LM Studio, llama.cpp…) needs
    # only allow_ai; a service on another computer also needs network_enabled
    # and allow_ai_remote.
    # Saving pages to the Internet Archive publishes their addresses there, so it
    # has its own switch (plus the master switch). Keys raise the daily limit.
    allow_archive_submit: bool = False
    # Pages on your own computer or network (a home server, router, NAS) are
    # never fetched unless you allow it — and the web may never redirect there.
    allow_private_addresses: bool = False
    ia_keys: str = ""           # "access:secret" from archive.org/account/s3.php
    allow_ai: bool = False
    allow_ai_remote: bool = False
    ai_endpoint: str = "http://localhost:11434/v1"   # OpenAI-compatible base URL
    ai_model: str = ""
    ai_api_key: str = ""        # or set CHRONOS_AI_KEY in the environment

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class Config:
    """Resolves paths and loads/saves settings. Creates the app dir on demand."""

    def __init__(self, app_dir: Path | None = None):
        self.app_dir = Path(app_dir) if app_dir else default_app_dir()
        self.db_path = self.app_dir / "bookmarks.db"
        self.settings_path = self.app_dir / "settings.json"
        self.favicons_dir = self.app_dir / "favicons"
        self.archives_dir = self.app_dir / "archives"
        self.inbox_dir = self.app_dir / "inbox"
        self.outbox_dir = self.app_dir / "outbox"
        self._settings: Settings | None = None

    def ensure_dirs(self) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.favicons_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = self.load_settings()
        return self._settings

    def load_settings(self) -> Settings:
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                return Settings.from_dict(data)
            except (json.JSONDecodeError, OSError):
                # Corrupt settings must never lose bookmark data or crash import.
                return Settings()
        return Settings()

    def save_settings(self, settings: Settings) -> None:
        self.ensure_dirs()
        tmp = self.settings_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.settings_path)  # atomic on same filesystem
        self._settings = settings
