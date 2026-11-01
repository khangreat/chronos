"""Importer framework.

Each importer converts a browser's native bookmark store into a list of
`Bookmark` objects with a *canonical* timestamp (UNIX seconds, UTC). The two
epoch conventions in the wild are handled here so no downstream code has to care:

  - Firefox family: dateAdded is microseconds since the UNIX epoch (1970).
  - Chromium family: date_added is microseconds since 1601-01-01 (WebKit epoch).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Type

from ..core.models import Bookmark

# Seconds between 1601-01-01 and 1970-01-01.
_WEBKIT_EPOCH_OFFSET = 11_644_473_600


def firefox_micros_to_unix(micros: int) -> int:
    return int(micros) // 1_000_000 if micros else 0


def webkit_micros_to_unix(micros: int) -> int:
    if not micros:
        return 0
    return int(micros) // 1_000_000 - _WEBKIT_EPOCH_OFFSET


class BrowserImporter:
    """Base importer. Subclasses set `name` and implement `parse(path)`."""

    name: str = "Generic"

    def default_paths(self) -> List[Path]:
        """Candidate profile locations; empty by default."""
        return []

    def parse(self, source: Path) -> List[Bookmark]:  # pragma: no cover - abstract
        raise NotImplementedError

    def find_source(self) -> Optional[Path]:
        for p in self.default_paths():
            if p.exists():
                return p
        return None

    @staticmethod
    def _readonly_copy(db_path: Path) -> Path:
        """Copy a possibly-locked sqlite file to a temp path we can read freely."""
        tmp = Path(tempfile.mkdtemp(prefix="chronos_")) / db_path.name
        shutil.copy2(db_path, tmp)
        return tmp


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: Dict[str, Type[BrowserImporter]] = {}


def register(cls: Type[BrowserImporter]) -> Type[BrowserImporter]:
    _REGISTRY[cls.name.lower()] = cls
    return cls


def get_importer(name: str) -> Optional[BrowserImporter]:
    cls = _REGISTRY.get(name.lower())
    return cls() if cls else None


def all_importers() -> List[BrowserImporter]:
    return [cls() for cls in _REGISTRY.values()]
