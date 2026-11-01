"""Lightweight i18n — JSON string tables with English as the base.

Each locale is a JSON file under `locale/`. A missing or empty value falls back
to English, so a partially-translated locale (like the Brahui scaffold) still
renders — English where it isn't translated yet. RTL locales flip the whole app
layout direction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

_LOCALE_DIR = Path(__file__).parent / "locale"

# Locales that render right-to-left.
RTL_LOCALES = {"ar", "brh", "fa", "ur", "he", "ps", "sd"}


class Translator:
    def __init__(self, locale: str = "en"):
        self._base: Dict[str, str] = self._load("en")
        self.locale = "en"
        self._cat: Dict[str, str] = {}
        self.set_locale(locale)

    @staticmethod
    def _load(loc: str) -> Dict[str, str]:
        p = _LOCALE_DIR / f"{loc}.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return {k: v for k, v in data.items() if not k.startswith("_")}
            except (ValueError, OSError):
                return {}
        return {}

    def set_locale(self, locale: str) -> None:
        self.locale = locale or "en"
        self._cat = self._load(self.locale)

    def tr(self, key: str, **fmt) -> str:
        s = self._cat.get(key) or self._base.get(key) or key
        return s.format(**fmt) if fmt else s

    @property
    def is_rtl(self) -> bool:
        return self.locale in RTL_LOCALES


def available_locales() -> List[str]:
    return sorted(p.stem for p in _LOCALE_DIR.glob("*.json"))


# module-level active translator
_active = Translator("en")


def set_locale(locale: str) -> None:
    _active.set_locale(locale)


def tr(key: str, **fmt) -> str:
    return _active.tr(key, **fmt)


def is_rtl() -> bool:
    return _active.is_rtl


def active_locale() -> str:
    return _active.locale
