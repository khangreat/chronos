"""Chromium-family importers.

Chromium stores bookmarks in a JSON file literally named "Bookmarks" (no
extension), NOT in a sqlite DB — a common thing to get wrong. Timestamps are
microseconds since the WebKit/1601 epoch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from ..core.models import Bookmark
from .base import BrowserImporter, register, webkit_micros_to_unix


class ChromiumImporter(BrowserImporter):
    name = "Chromium"
    # Subdir under the platform config root, e.g. "Google/Chrome".
    vendor_subdir: str = ""

    def _config_root(self) -> Path:
        home = Path.home()
        if sys.platform.startswith("win"):
            return home / "AppData/Local"
        if sys.platform == "darwin":
            return home / "Library/Application Support"
        return home / ".config"

    def default_paths(self) -> List[Path]:
        from .profiles import discover
        return [p.bookmarks for p in discover()
                if p.family == "chromium" and p.browser == self.name and p.bookmarks]

    def parse(self, source: Path) -> List[Bookmark]:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        out: List[Bookmark] = []
        roots = data.get("roots", {})
        for root_name, node in roots.items():
            if isinstance(node, dict):
                self._walk(node, folder=None, out=out)
        return out

    def _walk(self, node: dict, folder: Optional[str], out: List[Bookmark]) -> None:
        ntype = node.get("type")
        if ntype == "url":
            url = node.get("url")
            if url and not url.startswith("javascript:"):
                out.append(
                    Bookmark(
                        url=url,
                        title=node.get("name") or url,
                        date_added=webkit_micros_to_unix(
                            int(node.get("date_added", 0) or 0)
                        ),
                        browser=self.name,
                        folder_name=folder,
                    )
                )
        elif ntype == "folder":
            fname = node.get("name") or folder
            for child in node.get("children", []):
                self._walk(child, folder=fname, out=out)


@register
class ChromeImporter(ChromiumImporter):
    name = "Chrome"
    vendor_subdir = "Google/Chrome"


@register
class EdgeImporter(ChromiumImporter):
    name = "Edge"
    vendor_subdir = "Microsoft/Edge"


@register
class BraveImporter(ChromiumImporter):
    name = "Brave"
    vendor_subdir = "BraveSoftware/Brave-Browser"


@register
class VivaldiImporter(ChromiumImporter):
    name = "Vivaldi"
    vendor_subdir = "Vivaldi"


@register
class OperaImporter(ChromiumImporter):
    name = "Opera"
    vendor_subdir = "com.operasoftware.Opera"
