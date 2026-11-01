"""Export / interchange format writers. Pure functions over domain objects.

Formats (chosen from current interchange practice):
  - Citations: CSL-JSON (primary), BibTeX (@online), RIS (TY ELEC)
  - Feeds: OPML 2.0 (+ a reader)
  - Quotes: W3C Web Annotation Data Model (+ Markdown for pasting)
  - Bookmarks: Netscape HTML (re-importable), JSON, CSV
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from ..core.models import Bookmark
from ..interop import bookmark_to_csl


def _iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _year(ts: Optional[int]) -> Optional[int]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).year


# --------------------------------------------------------------------------- #
# Citations
# --------------------------------------------------------------------------- #
def to_csl_json(bookmarks: List[Bookmark]) -> str:
    return json.dumps([bookmark_to_csl(b) for b in bookmarks],
                      ensure_ascii=False, indent=2)


def _cite_key(b: Bookmark) -> str:
    base = (b.byline or b.site_name or b.title or "web").split()
    first = re.sub(r"[^A-Za-z0-9]", "", base[0]) if base else "web"
    yr = _year(b.published_ts or b.date_added) or ""
    return f"{first.lower() or 'web'}{yr}{b.id or ''}"


_TEX = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
        "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}"}


def _tex(value) -> str:
    """Escape LaTeX specials so a title like 'Q&A: 50% off #1' still compiles."""
    return "".join(_TEX.get(ch, ch) for ch in str(value))


def to_bibtex(bookmarks: List[Bookmark]) -> str:
    """biblatex @online entries. `date` is the publication date only when known —
    the day you bookmarked something isn't when it was published; that goes in
    `urldate`. An Internet Archive copy goes in `addendum`."""
    out = []
    for b in bookmarks:
        authors = " and ".join(a.strip() for a in
                               (b.byline or "").replace(" and ", ",").split(",") if a.strip())
        fields = {
            "title": _tex(b.page_title or b.title) if (b.page_title or b.title) else None,
            "author": _tex(authors) if authors else None,
            "organization": _tex(b.site_name) if b.site_name else None,
            "date": _iso(b.published_ts),
            "url": b.url,
            "urldate": _iso(b.fetched_at or b.date_added),
            "addendum": (f"Archived at \\url{{{b.wayback_url}}}"
                         if getattr(b, "wayback_url", None) else None),
            "note": _tex(b.notes) if b.notes else None,
        }
        body = ",\n".join(
            f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        out.append(f"@online{{{_cite_key(b)},\n{body}\n}}")
    return "\n\n".join(out) + ("\n" if out else "")


def to_ris(bookmarks: List[Bookmark]) -> str:
    lines = []
    for b in bookmarks:
        rec = ["TY  - ELEC", f"TI  - {b.page_title or b.title}"]
        for a in (b.byline or "").replace(" and ", ",").split(","):
            if a.strip():
                rec.append(f"AU  - {a.strip()}")
        if b.published_ts:                        # published, not bookmarked
            rec.append(f"PY  - {_year(b.published_ts)}")
            rec.append(f"DA  - {datetime.fromtimestamp(b.published_ts, tz=timezone.utc):%Y/%m/%d}")
        if b.site_name:
            rec.append(f"PB  - {b.site_name}")
        if b.excerpt:
            rec.append(f"AB  - {b.excerpt}")
        rec.append(f"UR  - {b.url}")
        if getattr(b, "wayback_url", None):
            rec.append(f"L2  - {b.wayback_url}")
        acc = _iso(b.fetched_at or b.date_added)
        if acc:
            rec.append(f"Y2  - {acc}")
        rec.append("ER  - ")
        lines.append("\n".join(rec))
    return "\n\n".join(lines) + ("\n" if lines else "")


# --------------------------------------------------------------------------- #
# Feeds — OPML 2.0
# --------------------------------------------------------------------------- #
def feeds_to_opml(feeds: List[dict]) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<opml version="2.0">', "  <head><title>Chronos feeds</title></head>",
             "  <body>"]
    for f in feeds:
        title = xml_escape(f.get("title") or f.get("url"), {'"': "&quot;"})
        url = xml_escape(f.get("url"), {'"': "&quot;"})
        site = xml_escape(f.get("site_url") or "", {'"': "&quot;"})
        parts.append(
            f'    <outline type="rss" text="{title}" title="{title}" '
            f'xmlUrl="{url}" htmlUrl="{site}"/>')
    parts += ["  </body>", "</opml>"]
    return "\n".join(parts) + "\n"


def opml_to_feed_urls(opml_text: str) -> List[dict]:
    out = []
    try:
        root = ET.fromstring(opml_text)
    except ET.ParseError:
        return out
    for node in root.iter("outline"):
        xml_url = node.get("xmlUrl")
        if xml_url:
            out.append({"url": xml_url,
                        "title": node.get("title") or node.get("text") or "",
                        "site_url": node.get("htmlUrl") or None})
    return out


# --------------------------------------------------------------------------- #
# Quotes — W3C Web Annotation Data Model
# --------------------------------------------------------------------------- #
def _is_rtl(text: str) -> bool:
    return any("\u0590" <= c <= "\u08FF" for c in text)  # Hebrew/Arabic/Syriac ranges


def quotes_to_web_annotations(quotes: List[dict]) -> str:
    """`quotes` are interop quote dicts: {quote, note, locator, source(CSL)}."""
    anns = []
    for i, q in enumerate(quotes):
        src = q.get("source") or {}
        url = src.get("URL", "")
        target = {
            "source": url,
            "selector": {"type": "TextQuoteSelector", "exact": q["quote"]},
        }
        ann = {
            "@context": "http://www.w3.org/ns/anno.jsonld",
            "type": "Annotation",
            "id": f"urn:chronos:quote:{i + 1}",
            "motivation": "highlighting",
            "target": target,
            # carry the full CSL source so a consumer can cite it directly
            "_source_csl": src,
        }
        if _is_rtl(q["quote"]):
            target["selector"]["language"] = "und"
            ann["textDirection"] = "rtl"
        bodies = []
        if q.get("note"):
            bodies.append({"type": "TextualBody", "value": q["note"],
                           "purpose": "commenting"})
        if q.get("locator"):
            bodies.append({"type": "TextualBody", "value": q["locator"],
                           "purpose": "identifying"})
        if bodies:
            ann["body"] = bodies
        anns.append(ann)
    return json.dumps(anns, ensure_ascii=False, indent=2)


def quotes_to_markdown(quotes: List[dict]) -> str:
    out = []
    for q in quotes:
        src = q.get("source") or {}
        loc = f" ({q['locator']})" if q.get("locator") else ""
        cite_bits = [src.get("title", ""), src.get("container-title", "")]
        issued = src.get("issued", {}).get("date-parts", [[None]])[0]
        if issued and issued[0]:
            cite_bits.append(str(issued[0]))
        if src.get("URL"):
            cite_bits.append(src["URL"])
        cite = " · ".join(b for b in cite_bits if b)
        block = f"> {q['quote']}{loc}\n>\n> — {cite}"
        if q.get("note"):
            block += f"\n>\n> Note: {q['note']}"
        out.append(block)
    return "\n\n".join(out) + ("\n" if out else "")


# --------------------------------------------------------------------------- #
# Bookmarks
# --------------------------------------------------------------------------- #
def to_netscape_html(bookmarks: List[Bookmark]) -> str:
    rows = []
    for b in bookmarks:
        tags = f' TAGS="{escape(",".join(b.tags))}"' if b.tags else ""
        rows.append(
            f'    <DT><A HREF="{escape(b.url)}" ADD_DATE="{b.date_added}"{tags}>'
            f'{escape(b.title or b.url)}</A>')
    body = "\n".join(rows)
    return ("<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
            "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">\n"
            "<TITLE>Bookmarks</TITLE>\n<H1>Chronos Bookmarks</H1>\n"
            f"<DL><p>\n{body}\n</DL><p>\n")


def to_json(bookmarks: List[Bookmark]) -> str:
    def d(b: Bookmark):
        return {"url": b.url, "title": b.title, "browser": b.browser,
                "date_added": b.date_added, "folder": b.folder_name,
                "tags": b.tags, "favorite": b.is_favorite,
                "site_name": b.site_name, "byline": b.byline,
                "published_ts": b.published_ts, "excerpt": b.excerpt}
    return json.dumps([d(b) for b in bookmarks], ensure_ascii=False, indent=2)


def to_csv(bookmarks: List[Bookmark]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["url", "title", "browser", "date_iso", "tags", "favorite",
                "site_name", "folder"])
    for b in bookmarks:
        w.writerow([b.url, b.title, b.browser, f"{b.dt:%Y-%m-%d}",
                    ";".join(b.tags), int(b.is_favorite),
                    b.site_name or "", b.folder_name or ""])
    return buf.getvalue()
