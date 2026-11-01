"""Extract clean article text + citation metadata from HTML.

`extract_content(html, url)` is a pure function — no network — so it's the unit
we test hard. The fetcher (which does touch the network, gated) just calls it.

Uses only the standard library. If the user has installed trafilatura or
readability, we use them for better main-text extraction; we NEVER install them.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional
from urllib.parse import urlparse

try:
    import trafilatura  # type: ignore
    _HAS_TRAFILATURA = True
except Exception:  # pragma: no cover
    _HAS_TRAFILATURA = False

try:
    from readability import Document as _ReadabilityDoc  # type: ignore
    _HAS_READABILITY = True
except Exception:  # pragma: no cover
    _HAS_READABILITY = False


@dataclass
class ExtractedPage:
    url: str
    title: Optional[str] = None
    site_name: Optional[str] = None
    byline: Optional[str] = None
    published_ts: Optional[int] = None
    excerpt: Optional[str] = None
    text: str = ""
    extractor: str = "builtin"
    meta: Dict[str, str] = field(default_factory=dict)


_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}
_BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br"}


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: Dict[str, str] = {}
        self.title_parts: List[str] = []
        self._in_title = False
        self._skip_depth = 0
        self._article_depth = 0
        self._chunks: List[str] = []          # all body text
        self._article_chunks: List[str] = []  # text inside <article>/<main>

    def handle_starttag(self, tag, attrs):
        d = {k.lower(): (v or "") for k, v in attrs}
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = d.get("property") or d.get("name")
            if key and "content" in d:
                self.meta.setdefault(key.lower(), d["content"])
        elif tag in ("article", "main"):
            self._article_depth += 1
        elif tag == "time" and "datetime" in d:
            self.meta.setdefault("_time_datetime", d["datetime"])

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in ("article", "main") and self._article_depth:
            self._article_depth -= 1
        elif tag in _BLOCK and self._skip_depth == 0:
            self._chunks.append("\n")
            if self._article_depth:
                self._article_chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        if data.strip():
            self._chunks.append(data)
            if self._article_depth:
                self._article_chunks.append(data)


def _collapse(text: str) -> str:
    text = _html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _parse_date(raw: str) -> Optional[int]:
    if not raw:
        return None
    raw = raw.strip()
    fmts = ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%B %d, %Y"]
    for f in fmts:
        try:
            dt = datetime.strptime(raw.replace("Z", "+0000") if f.endswith("%z") else raw, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return int(datetime(y, mo, d, tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    return None


def extract_content(html_text: str, url: str) -> ExtractedPage:
    p = _Parser()
    try:
        p.feed(html_text)
    except Exception:
        pass
    meta = p.meta
    domain = urlparse(url).netloc.lower().lstrip("www.") if url else None

    title = (meta.get("og:title") or "".join(p.title_parts).strip() or None)
    site_name = meta.get("og:site_name") or domain
    byline = (meta.get("author") or meta.get("article:author")
              or meta.get("twitter:creator") or None)
    excerpt = meta.get("og:description") or meta.get("description") or None
    published_ts = _parse_date(
        meta.get("article:published_time") or meta.get("date")
        or meta.get("pubdate") or meta.get("_time_datetime") or ""
    )

    # Prefer explicit <article>/<main> text, else full body.
    builtin_text = _collapse("".join(p._article_chunks) or "".join(p._chunks))

    text, extractor = builtin_text, "builtin"
    if _HAS_TRAFILATURA:  # pragma: no cover - optional path
        try:
            t = trafilatura.extract(html_text, url=url) or ""
            if len(t) > len(text):
                text, extractor = _collapse(t), "trafilatura"
        except Exception:
            pass
    elif _HAS_READABILITY:  # pragma: no cover - optional path
        try:
            doc = _ReadabilityDoc(html_text)
            inner = _Parser()
            inner.feed(doc.summary())
            t = _collapse("".join(inner._chunks))
            if len(t) > len(text):
                text, extractor = t, "readability"
        except Exception:
            pass

    if not excerpt and text:
        excerpt = text[:280].rsplit(" ", 1)[0] + "…" if len(text) > 280 else text

    return ExtractedPage(
        url=url, title=title, site_name=site_name, byline=byline,
        published_ts=published_ts, excerpt=excerpt, text=text,
        extractor=extractor, meta=meta,
    )
