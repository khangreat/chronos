"""ArchiveService — save an offline copy of a page.

Stores the raw HTML gzipped on disk (files-as-truth, under the app's archives
dir) and the extracted readable text in the DB. This gives a local snapshot that
survives the source going dead — independent of, and complementary to, the
Wayback fallback.

Note: resources (images/CSS/JS) are NOT inlined — this is a content archive
(source HTML + readable text), not a pixel-perfect page capture. Rendering a
page with all assets would need a browser engine, which Chronos deliberately
avoids. The extracted text is the readable offline copy; the gzipped HTML is the
provenance record.
"""

from __future__ import annotations

import gzip
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .extract import ExtractedPage, extract_content
from .fetcher import PageFetcher


@dataclass
class ArchiveResult:
    bookmark_id: int
    path: str
    bytes: int
    sha1: str


class ArchiveService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.dir = Path(ctx.config.archives_dir)
        self.fetcher = PageFetcher(ctx.network)

    def archive_from_html(self, bookmark_id: int, html: str,
                          url: str = "", extractor: Optional[str] = None) -> ArchiveResult:
        """Save an offline copy from HTML already in hand (no network)."""
        bm = self.ctx.storage.get(bookmark_id)
        if bm is None:
            raise ValueError(f"No bookmark id={bookmark_id}")
        data = html.encode("utf-8", "replace")
        sha1 = hashlib.sha1(data).hexdigest()
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{sha1}.html.gz"
        with gzip.open(path, "wb") as f:
            f.write(data)
        # also store the readable extraction so the reader/search benefit
        page = extract_content(html, url or bm.url, extractor or
                               getattr(self.ctx.config.settings, "prefer_extractor", "auto"))
        self.ctx.content.store_extracted(bookmark_id, page)
        # best-ref: enrich author/site/date/description from page metadata
        try:
            from .metadata import extract_meta
            self.ctx.storage.enrich_metadata(bookmark_id, extract_meta(html))
        except Exception:
            pass
        try:                                   # videos the page shows or links
            self.ctx.videos.scan_page(bookmark_id, html)
        except Exception:
            pass
        self.ctx.storage.add_archive(bookmark_id, str(path), sha1,
                                     len(data), int(time.time()))
        return ArchiveResult(bookmark_id, str(path), len(data), sha1)

    def archive(self, bookmark_id: int) -> ArchiveResult:
        """Fetch (gated by page_fetch) and keep a copy, following the site's
        rule. Raises with a plain reason when nothing could be kept."""
        from .fetch_queue import FetchEngine
        r = FetchEngine(self.ctx).fetch_one(bookmark_id)
        if r.status not in ("ok", "moved"):
            raise RuntimeError(r.reason or r.status)
        rec = self.ctx.storage.get_archive(bookmark_id)
        if rec is None:
            raise RuntimeError(r.reason or "Nothing was kept.")
        return ArchiveResult(bookmark_id, rec["path"], rec["bytes"], rec["sha1"])

    def keep(self, bookmark_id: int, out, extractor: Optional[str] = None) -> str:
        """Keep what a fetch brought back (a FetchOutcome): a web page, a PDF
        (with its text, for search and reading) or plain text. Returns the kind."""
        url = out.final_url or out.url
        if out.kind == "html":
            self.archive_from_html(bookmark_id, out.text(), url, extractor)
            return "html"
        if out.kind == "pdf":
            text, title = pdf_text(out.body)
            self._store_file(bookmark_id, out.body, ".pdf.gz", "application/pdf")
            self.ctx.content.store_extracted(bookmark_id, ExtractedPage(
                url=url, title=title, text=text, excerpt=text[:280] or None,
                extractor="pdf"))
            return "pdf"
        if out.kind == "text":
            text = out.text()
            self._store_file(bookmark_id, out.body, ".txt.gz", "text/plain")
            self.ctx.content.store_extracted(bookmark_id, ExtractedPage(
                url=url, text=text, excerpt=text[:280] or None, extractor="text"))
            return "text"
        return ""

    def _store_file(self, bookmark_id: int, data: bytes, suffix: str, mime: str) -> None:
        sha1 = hashlib.sha1(data).hexdigest()
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{sha1}{suffix}"
        if not path.exists():
            with gzip.open(path, "wb") as f:
                f.write(data)
        self.ctx.storage.add_archive(bookmark_id, str(path), sha1, len(data),
                                     int(time.time()), mime)

    def read_bytes(self, bookmark_id: int) -> Optional[bytes]:
        rec = self.ctx.storage.get_archive(bookmark_id)
        if not rec or not Path(rec["path"]).exists():
            return None
        with gzip.open(rec["path"], "rb") as f:
            return f.read()

    # -- the Internet Archive -------------------------------------------- #
    def save_to_internet_archive(self, bookmark_id: int, **kw) -> str:
        """Ask the Internet Archive to capture this page; remember the snapshot."""
        from .archive_org import save_page_now
        bm = self.ctx.storage.get(bookmark_id)
        if bm is None:
            raise ValueError(f"No item id={bookmark_id}")
        if not bm.url.startswith(("http://", "https://")):
            raise ValueError("This item has no web address to save.")
        snap = save_page_now(bm.url, self.ctx.config.settings, self.ctx.network, **kw)
        self.ctx.storage.set_wayback(bookmark_id, snap)
        return snap

    def save_many_to_internet_archive(self, ids, sleep=None, **kw) -> dict:
        """Save several, one at a time, spaced to stay within the Archive's limits."""
        import time as _t
        from .archive_org import ArchiveError, wait_between
        sleep = sleep or _t.sleep
        gap = wait_between(self.ctx.config.settings)
        saved, failed = [], []
        for n, i in enumerate(ids):
            if n:
                sleep(gap)
            try:
                saved.append(self.save_to_internet_archive(i, sleep=sleep, **kw))
            except (ArchiveError, ValueError) as e:
                failed.append((i, str(e)))
                if "too many" in str(e):          # rate limited: stop, don't hammer
                    break
        return {"saved": saved, "failed": failed}

    def has_archive(self, bookmark_id: int) -> bool:
        return self.ctx.storage.get_archive(bookmark_id) is not None

    def read_html(self, bookmark_id: int) -> Optional[str]:
        rec = self.ctx.storage.get_archive(bookmark_id)
        if not rec or (rec.get("mime") or "text/html") != "text/html":
            return None                                # a PDF or text copy
        p = Path(rec["path"])
        if not p.exists():
            return None
        with gzip.open(p, "rb") as f:
            return f.read().decode("utf-8", "replace")

    def remove(self, bookmark_id: int) -> bool:
        """Remove a bookmark's archive: delete the gz file, then the DB row.
        Safe to call when there is no archive. Returns True if one was removed."""
        rec = self.ctx.storage.get_archive(bookmark_id)
        if not rec:
            return False
        self.ctx.storage.delete_archive(bookmark_id)
        # Copies are named by their content, so two items with the same page
        # share one file: only remove it when nothing else uses it.
        shared = self.ctx.storage.conn.execute(
            "SELECT 1 FROM archives WHERE path=? LIMIT 1", (rec["path"],)).fetchone()
        if not shared:
            try:
                Path(rec["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def purge_orphans(self) -> int:
        """Delete archive files on disk that no DB row references. The DB is the
        truth; derived files that lost their row are safe to remove."""
        referenced = {a["path"] for a in self.ctx.storage.all_archives()}
        removed = 0
        for f in self.dir.glob("*.gz"):
            if str(f) not in referenced:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


def pdf_text(data: bytes):
    """(text, title) of a PDF — with pypdf when available (the Windows build
    includes it); otherwise empty text, and the PDF is still kept."""
    try:
        import io

        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        title = None
        try:
            title = (r.metadata.title or None) if r.metadata else None
        except Exception:
            pass
        pages = []
        for page in r.pages[:500]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(p.strip() for p in pages if p.strip())
        return text, title
    except Exception:
        return "", None
