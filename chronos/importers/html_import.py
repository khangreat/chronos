"""Netscape-format HTML bookmark importer (the universal export format).

Every browser can export to this format, so it's the portable path. Parses
<DT><A HREF="..." ADD_DATE="..."> anchors and tracks the enclosing <H3> folder.
ADD_DATE is UNIX seconds (occasionally milliseconds — normalised below).
"""

from __future__ import annotations

import html.parser
from pathlib import Path
from typing import List, Optional

from ..core.models import Bookmark
from .base import BrowserImporter, register


def _normalise_add_date(raw: Optional[str]) -> int:
    if not raw:
        return 0
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 0
    # 13+ digit values are milliseconds; fold to seconds.
    return v // 1000 if v > 10_000_000_000 else v


class _NetscapeParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.bookmarks: List[Bookmark] = []
        self._folder_stack: List[str] = []
        self._pending_href: Optional[str] = None
        self._pending_date: int = 0
        self._capture_h3 = False
        self._capture_a = False
        self._h3_text = ""
        self._a_text = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "h3":
            self._capture_h3 = True
            self._h3_text = ""
        elif tag == "a":
            self._pending_href = d.get("href")
            self._pending_date = _normalise_add_date(d.get("add_date"))
            self._capture_a = True
            self._a_text = ""
        elif tag == "dl":
            # Entering a folder scope; the most recent H3 is its title.
            if self._h3_text:
                self._folder_stack.append(self._h3_text)
                self._h3_text = ""

    def handle_endtag(self, tag):
        if tag == "h3":
            self._capture_h3 = False
        elif tag == "a":
            self._capture_a = False
            if self._pending_href and not self._pending_href.startswith("javascript:"):
                folder = self._folder_stack[-1] if self._folder_stack else None
                self.bookmarks.append(
                    Bookmark(
                        url=self._pending_href,
                        title=self._a_text.strip() or self._pending_href,
                        date_added=self._pending_date,
                        browser="HTML",
                        folder_name=folder,
                    )
                )
            self._pending_href = None
        elif tag == "dl":
            if self._folder_stack:
                self._folder_stack.pop()

    def handle_data(self, data):
        if self._capture_h3:
            self._h3_text += data
        elif self._capture_a:
            self._a_text += data


@register
class HTMLImporter(BrowserImporter):
    name = "HTML"

    def parse(self, source: Path) -> List[Bookmark]:
        text = Path(source).read_text(encoding="utf-8", errors="replace")
        p = _NetscapeParser()
        p.feed(text)
        return p.bookmarks
