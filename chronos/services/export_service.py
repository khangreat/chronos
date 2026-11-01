"""ExportService — turn the store into interchange files.

Dispatches a format name to the right writer over the right dataset (bookmarks,
feeds, or captured quotes). `export(fmt)` returns a string; `export_to(fmt,
path)` writes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..core.models import Bookmark
from ..export import exporters as X

FORMATS = {
    # citations (over bookmarks)
    "csl": (".json", "citation"),
    "bibtex": (".bib", "citation"),
    "ris": (".ris", "citation"),
    # bookmarks
    "html": (".html", "bookmarks"),
    "json": (".json", "bookmarks"),
    "csv": (".csv", "bookmarks"),
    # feeds
    "opml": (".opml", "feeds"),
    # quotes
    "annotations": (".json", "quotes"),
    "quotes-md": (".md", "quotes"),
}


class ExportService:
    def __init__(self, ctx):
        self.ctx = ctx

    def export(self, fmt: str, bookmarks: Optional[List[Bookmark]] = None) -> str:
        if fmt not in FORMATS:
            raise ValueError(f"Unknown format: {fmt}. Known: {', '.join(FORMATS)}")
        kind = FORMATS[fmt][1]
        if kind in ("citation", "bookmarks"):
            data = bookmarks if bookmarks is not None \
                else self.ctx.storage.all_bookmarks()
            return {
                "csl": X.to_csl_json, "bibtex": X.to_bibtex, "ris": X.to_ris,
                "html": X.to_netscape_html, "json": X.to_json, "csv": X.to_csv,
            }[fmt](data)
        if kind == "feeds":
            return X.feeds_to_opml(self.ctx.storage.list_feeds())
        if kind == "quotes":
            quotes = self.ctx.provider().list_quotes()
            return (X.quotes_to_web_annotations(quotes) if fmt == "annotations"
                    else X.quotes_to_markdown(quotes))
        raise ValueError(kind)  # pragma: no cover

    def export_to(self, fmt: str, path: Path,
                  bookmarks: Optional[List[Bookmark]] = None) -> Path:
        path = Path(path)
        path.write_text(self.export(fmt, bookmarks), encoding="utf-8")
        return path

    def default_suffix(self, fmt: str) -> str:
        return FORMATS[fmt][0]
