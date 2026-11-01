"""Interop — Chronos's implementation of the shared `bridgespec` contract.

The contract types and protocols (CitationProvider, LinkProvider, QuoteProvider,
LinkRef, Quotation) now live in the neutral `bridgespec` package, so Chronos,
Command Center, Nawishtar, and ytman all speak one versioned definition instead
of duplicating it. This module maps Chronos's data onto that contract and
re-exports the names for backward compatibility.

Integration model: each app exposes a provider; Command Center is the broker
(bridgespec.ProviderRegistry) that routes requests. `ChronosProvider(ctx)` is
Chronos's implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bridgespec import (  # the shared, versioned contract
    CONTRACT_VERSION, CitationProvider, LinkProvider, LinkRef, ProviderRegistry,
    Quotation, QuoteProvider, ResourceProvider, ResourceRef, validate_csl_item,
)

from .core.context import ApplicationContext
from .core.models import Bookmark

__all__ = [
    "ChronosProvider", "bookmark_to_csl", "LinkRef", "Quotation", "ResourceRef",
    "CitationProvider", "LinkProvider", "QuoteProvider", "ResourceProvider",
    "ProviderRegistry", "CONTRACT_VERSION", "validate_csl_item",
]


# --------------------------------------------------------------------------- #
# CSL-JSON building
# --------------------------------------------------------------------------- #
def _date_parts(ts: Optional[int]) -> Optional[Dict[str, Any]]:
    if not ts:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return {"date-parts": [[dt.year, dt.month, dt.day]]}


def _authors(byline: Optional[str]) -> Optional[List[Dict[str, str]]]:
    if not byline:
        return None
    out: List[Dict[str, str]] = []
    for name in [n.strip() for n in byline.replace(" and ", ",").split(",")]:
        if not name:
            continue
        parts = name.split()
        if len(parts) >= 2:
            out.append({"family": parts[-1], "given": " ".join(parts[:-1])})
        else:
            out.append({"literal": name})
    return out or None


_CSL_TYPE_BY_KIND = {
    "social_post": "post",
    "social_comment": "post",
    "thread": "post",
    "article": "article-newspaper",
    "feed_entry": "webpage",
    "webpage": "webpage",
    "image": "graphic",
    "video": "motion_picture",
}


def bookmark_to_csl(bm: Bookmark, accessed_ts: Optional[int] = None) -> Dict[str, Any]:
    """Produce a CSL-JSON item from a resource, typed by its kind (a saved tweet
    becomes a 'post', a news article 'article-newspaper', etc.)."""
    item: Dict[str, Any] = {
        "id": f"chronos-{bm.id}" if bm.id else "chronos-web",
        "type": _CSL_TYPE_BY_KIND.get(getattr(bm, "kind", "webpage"), "webpage"),
        "title": bm.page_title or bm.title,
        "URL": bm.url,
    }
    site = bm.site_name
    if site:
        item["container-title"] = site
    authors = _authors(bm.byline)
    if authors:
        item["author"] = authors
    issued = _date_parts(bm.published_ts)
    if issued:
        item["issued"] = issued
    accessed = _date_parts(accessed_ts) or _date_parts(bm.fetched_at) \
        or _date_parts(bm.date_added)
    if accessed:
        item["accessed"] = accessed
    if bm.excerpt:
        item["abstract"] = bm.excerpt
    if getattr(bm, "wayback_url", None):          # where a reader can still find it
        item["archive"] = "Internet Archive Wayback Machine"
        item["archive_location"] = bm.wayback_url
    return item


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class ChronosProvider:
    """Chronos's implementation of the interop contracts. Give it a context."""

    source_app = "chronos"

    def __init__(self, ctx: ApplicationContext):
        self.ctx = ctx

    # CitationProvider ------------------------------------------------------ #
    def resolve_citation(self, url: str) -> Optional[Dict[str, Any]]:
        """Return CSL-JSON for a URL Chronos knows. Works fully offline from
        stored metadata; if not stored and page_fetch is enabled, fetch first."""
        bm = self.ctx.storage.get_by_url(url)
        if bm is None:
            return None
        if not bm.has_content and self.ctx.network.is_allowed("page_fetch"):
            try:
                from .web.content_service import ContentService
                cs = ContentService(self.ctx.storage, self.ctx.network)
                cs.fetch_and_store(bm.id)  # type: ignore[arg-type]
                bm = self.ctx.storage.get(bm.id)  # type: ignore[arg-type]
            except Exception:
                pass  # fall back to whatever metadata we already have
        return bookmark_to_csl(bm)

    # LinkProvider ---------------------------------------------------------- #
    def find_links(self, pattern: str) -> List[LinkRef]:
        like = pattern if "%" in pattern else f"%{pattern}%"
        return [
            LinkRef(url=b.url, title=b.title, site=b.site_name,
                    date_added=b.date_added, source_app=self.source_app)
            for b in self.ctx.storage.find_by_url_pattern(like)
        ]

    def youtube_links(self) -> List[LinkRef]:
        """For ytman: every YouTube video in the archive — bookmarked directly or
        found inside saved pages — once each, at its canonical address."""
        refs: Dict[str, LinkRef] = {}
        for r in self.ctx.videos.refs():
            if r["platform"] != "youtube":
                continue
            site = r["found_on"][0]["title"] if r["found_on"] else None
            refs[r["url"]] = LinkRef(url=r["url"], title=r["title"], site=site,
                                     date_added=r["date_added"],
                                     source_app=self.source_app)
        # playlists, and any YouTube link not recognised as a single video
        # (kept as saved, so ytman still sees everything it used to)
        from .web.video import parse_video
        for pat in ("%youtube.com/playlist%", "%youtube.com/watch%", "%youtu.be/%",
                    "%youtube.com/shorts%"):
            for r in self.find_links(pat):
                v = parse_video(r.url)
                refs.setdefault(v.url if v else r.url, r)
        return list(refs.values())

    def video_refs(self, ids=None) -> List[Dict[str, Any]]:
        """Richer than LinkRef: platform, id, and every page a video was found
        on with the start time it pointed at."""
        return self.ctx.videos.refs(ids)

    # Quotations ------------------------------------------------------------ #
    def get_quote(self, snippet_id: int) -> Optional[Dict[str, Any]]:
        """A captured quote plus the CSL-JSON of its source, for Nawishtar to
        insert as a block quote + reference in one step."""
        snip = self.ctx.storage.get_snippet(snippet_id)
        if snip is None:
            return None
        source = self.ctx.storage.get(snip.bookmark_id)
        return Quotation(
            quote=snip.quote, note=snip.note, locator=snip.locator,
            source=bookmark_to_csl(source) if source else None,
            source_app=self.source_app,
        ).to_dict()

    def list_quotes(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for snip in self.ctx.storage.all_snippets():
            q = self.get_quote(snip.id)
            if q:
                out.append(q)
        return out

    # ResourceProvider ------------------------------------------------------ #
    def _resource_ref(self, bm: Bookmark) -> ResourceRef:
        rels: List[Dict[str, str]] = []
        for rel, other in self.ctx.resources.outgoing(bm.id):
            rels.append({"rel": rel, "url": other.url})
        for rel, other in self.ctx.resources.incoming(bm.id):
            rels.append({"rel": f"{rel}_by", "url": other.url})
        return ResourceRef(
            url=bm.url, title=bm.page_title or bm.title,
            kind=getattr(bm, "kind", "webpage"),
            csl=bookmark_to_csl(bm), author=bm.byline, site=bm.site_name,
            relationships=rels, source_app=self.source_app)

    def get_resource(self, url: str) -> Optional[Dict[str, Any]]:
        """A ResourceRef for a URL Chronos knows — kind, CSL, and how it relates
        to other resources (a reply's parent, a thread's members, a quoted post).
        Lets Nawishtar insert a captured post/thread as a structured reference."""
        bm = self.ctx.storage.get_by_url(url)
        if bm is None:
            return None
        return self._resource_ref(bm).to_dict()

    def resources_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        return [self._resource_ref(b).to_dict()
                for b in self.ctx.resources.by_kind(kind)]
