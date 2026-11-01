"""Best-ref metadata extractor.

Pulls the richest available reference metadata out of a page's HTML — Open Graph,
Twitter cards, standard <meta>, and JSON-LD — so a captured or archived resource
gets a proper author, site, description, and publish date instead of just a
title. Used to enrich resources on archive/capture, which makes their emitted
CSL citations far better.
"""

from __future__ import annotations

import html
import json
import re
from typing import Dict, Optional

from ..importers.platform._social import iso_ts


def _meta(htmltext: str, attr: str, value: str) -> Optional[str]:
    # <meta property="og:title" content="..."> in either attribute order
    pat1 = rf'<meta[^>]+{attr}=["\']{re.escape(value)}["\'][^>]+content=["\'](.*?)["\']'
    pat2 = rf'<meta[^>]+content=["\'](.*?)["\'][^>]+{attr}=["\']{re.escape(value)}["\']'
    for pat in (pat1, pat2):
        m = re.search(pat, htmltext, re.I | re.S)
        if m:
            return html.unescape(m.group(1).strip())
    return None


def _jsonld(htmltext: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            htmltext, re.I | re.S):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            nodes = data["@graph"]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            author = node.get("author")
            if isinstance(author, dict):
                author = author.get("name")
            elif isinstance(author, list) and author:
                a0 = author[0]
                author = a0.get("name") if isinstance(a0, dict) else a0
            publisher = node.get("publisher")
            if isinstance(publisher, dict):
                publisher = publisher.get("name")
            for k, v in (("author", author), ("site_name", publisher),
                         ("published", node.get("datePublished")),
                         ("title", node.get("headline") or node.get("name")),
                         ("description", node.get("description"))):
                if v and k not in out and isinstance(v, str):
                    out[k] = v.strip()
    return out


def extract_meta(htmltext: str) -> Dict[str, object]:
    """Return {title, author, site_name, description, published_ts} — only keys
    that were found."""
    htmltext = htmltext or ""
    ld = _jsonld(htmltext)
    title = (_meta(htmltext, "property", "og:title")
             or _meta(htmltext, "name", "twitter:title") or ld.get("title"))
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", htmltext, re.I | re.S)
        title = html.unescape(m.group(1).strip()) if m else None
    author = (_meta(htmltext, "name", "author")
              or _meta(htmltext, "property", "article:author") or ld.get("author"))
    site = (_meta(htmltext, "property", "og:site_name") or ld.get("site_name"))
    desc = (_meta(htmltext, "property", "og:description")
            or _meta(htmltext, "name", "twitter:description")
            or _meta(htmltext, "name", "description") or ld.get("description"))
    published = (_meta(htmltext, "property", "article:published_time")
                 or _meta(htmltext, "name", "date") or ld.get("published"))

    out: Dict[str, object] = {}
    if title:
        out["title"] = title
    if author:
        out["author"] = author
    if site:
        out["site_name"] = site
    if desc:
        out["description"] = desc
    ts = iso_ts(published) if isinstance(published, str) else None
    if ts:
        out["published_ts"] = ts
    return out
