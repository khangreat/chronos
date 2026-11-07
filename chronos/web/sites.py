"""Sites: what Chronos does with each site, and what it knows about them.

Every item belongs to a site (its domain, without "www."). Each site has a rule:

- fetch     — save pages normally (the default), one request at a time per site,
              `pace` seconds apart, so no site is hammered;
- metadata  — read only the title and author from the site's public oEmbed
              address (YouTube, Vimeo): the page itself belongs to ytman;
- login     — the site shows its posts only when you're logged in (X, Facebook,
              Instagram…): Chronos doesn't fetch it; the browser extension saves
              them from your own logged-in browser instead;
- skip      — never fetched (your choice, or a Google search page);
- private   — an address on your own computer or network (your router,
              localhost, 192.168.…): never fetched, and nothing on the web may
              redirect Chronos there.

Built-in rules cover the well-known sites; your own rules (the Sites window)
always win.
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, replace
from typing import Dict, List, Optional
from urllib.parse import urlsplit

MODES = ("fetch", "metadata", "login", "skip", "private")
MODE_LABELS = {
    "fetch": "Save pages",
    "metadata": "Titles only",
    "login": "Needs login — use the browser extension",
    "skip": "Never fetch",
    "private": "Your own network — never fetched",
}
DEFAULT_PACE = 2.0          # seconds between two requests to the same site


@dataclass(frozen=True)
class SiteRule:
    domain: str
    mode: str = "fetch"
    pace: float = DEFAULT_PACE
    extractor: Optional[str] = None      # None = the Settings choice
    note: str = ""
    builtin: bool = True

    @property
    def fetches(self) -> bool:
        return self.mode in ("fetch", "metadata")


_LOGIN = ("Shows posts only to logged-in visitors. Save them with the browser "
          "extension (right-click, Save to Chronos) from your own browser.")
BUILTIN: Dict[str, SiteRule] = {r.domain: r for r in [
    SiteRule("reddit.com", "login", note="Reddit refuses automatic fetching. On reddit.com, "
             "right-click: “Chronos: bring in my Reddit saved…” (browser extension)."),
    SiteRule("redd.it", "login", note="Reddit short links: see reddit.com."),
    SiteRule("x.com", "login", note=_LOGIN), SiteRule("twitter.com", "login", note=_LOGIN),
    SiteRule("facebook.com", "login", note=_LOGIN), SiteRule("fb.com", "login", note=_LOGIN),
    SiteRule("instagram.com", "login", note=_LOGIN), SiteRule("threads.net", "login", note=_LOGIN),
    SiteRule("linkedin.com", "login", note=_LOGIN), SiteRule("tiktok.com", "login", note=_LOGIN),
    SiteRule("pinterest.com", "login", note=_LOGIN), SiteRule("quora.com", "login", note=_LOGIN),
    SiteRule("mail.google.com", "login", note="Your mail — never fetched."),
    SiteRule("docs.google.com", "login", note="Your documents — open them in the browser."),
    SiteRule("drive.google.com", "login", note="Your files — open them in the browser."),
    SiteRule("youtube.com", "metadata", pace=1.0,
             note="Videos belong to ytman; Chronos reads each title and channel."),
    SiteRule("youtu.be", "metadata", pace=1.0, note="YouTube short links."),
    SiteRule("vimeo.com", "metadata", pace=1.0, note="Chronos reads each title and author."),
    SiteRule("web.archive.org", "fetch", pace=6.0, note="The Internet Archive asks for patience."),
    SiteRule("archive.org", "fetch", pace=6.0),
    SiteRule("wikipedia.org", "fetch", pace=1.0),
    SiteRule("github.com", "fetch", pace=2.0),
]}
# Google search result pages are searches you made, not pages to keep.
_SEARCH_PATHS = {"google.": "/search", "bing.com": "/search", "duckduckgo.com": "/"}


def domain_of(url: str) -> str:
    """The site an address belongs to: host without "www." (and without port)."""
    try:
        host = (urlsplit(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def is_private_host(host: str) -> bool:
    """An address on this computer or the local network (never fetched)."""
    host = (host or "").lower().strip("[]").rstrip(".")
    if not host:
        return True
    if host in ("localhost", "localhost.localdomain") or host.endswith(
            (".local", ".localhost", ".lan", ".home", ".internal", ".intranet", ".corp")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        pass
    return "." not in host                     # "router", "nas": single-label names


def is_private_url(url: str) -> bool:
    try:
        p = urlsplit(url or "")
    except ValueError:
        return True
    if p.scheme not in ("http", "https"):
        return True
    return is_private_host(p.hostname or "")


class SiteRules:
    """Rules for every site: yours (stored), else built in, else the default."""

    def __init__(self, storage, allow_private: bool = False):
        self.storage = storage
        self.allow_private = allow_private

    def _user(self, domain: str) -> Optional[SiteRule]:
        if getattr(self, "_cache", None) is None:          # all rules, read once
            self._cache = {r.domain: r for r in self.user_rules()}
        return self._cache.get(domain)

    def for_domain(self, domain: str) -> SiteRule:
        domain = (domain or "").lower()
        if is_private_host(domain) and not self.allow_private:
            return SiteRule(domain, "private", note=MODE_LABELS["private"])
        parts = domain.split(".")
        for i in range(max(1, len(parts) - 1)):  # "localhost" too            # sub.example.org → example.org
            cand = ".".join(parts[i:])
            u = self._user(cand)
            if u is not None:
                return replace(u, domain=domain) if cand != domain else u
        for i in range(max(1, len(parts) - 1)):  # "localhost" too
            cand = ".".join(parts[i:])
            if cand in BUILTIN:
                return replace(BUILTIN[cand], domain=domain)
        return SiteRule(domain)

    def for_url(self, url: str) -> SiteRule:
        web = (url or "").startswith(("http://", "https://"))
        if not web or (is_private_url(url) and not self.allow_private):
            return SiteRule(domain_of(url), "private", note=MODE_LABELS["private"])
        p = urlsplit(url)
        d = domain_of(url)
        for host, path in _SEARCH_PATHS.items():
            if host in d and p.path.startswith(path) and "q=" in (p.query or ""):
                return SiteRule(d, "skip", note="A search you made, not a page to keep.")
        return self.for_domain(d)

    def set(self, domain: str, mode: str, pace: float = DEFAULT_PACE,
            extractor: Optional[str] = None, note: str = "") -> None:
        if mode not in MODES or mode == "private":
            raise ValueError(f"Unknown rule: {mode}")
        self.storage.conn.execute(
            """INSERT INTO site_rules (domain, mode, pace, extractor, note, updated_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(domain) DO UPDATE SET
               mode=excluded.mode, pace=excluded.pace, extractor=excluded.extractor,
               note=excluded.note, updated_at=excluded.updated_at""",
            (domain.lower(), mode, max(0.0, float(pace)), extractor, note, int(time.time())))
        self.storage.conn.commit()
        self._cache = None

    def clear(self, domain: str) -> None:
        self.storage.conn.execute("DELETE FROM site_rules WHERE domain=?", (domain.lower(),))
        self.storage.conn.commit()
        self._cache = None

    def user_rules(self) -> List[SiteRule]:
        return [SiteRule(r["domain"], r["mode"], float(r["pace"] or DEFAULT_PACE),
                         r["extractor"] or None, r["note"] or "", builtin=False)
                for r in self.storage.conn.execute(
                    "SELECT * FROM site_rules ORDER BY domain")]


@dataclass
class SiteStats:
    domain: str
    items: int
    offline: int
    dead: int
    problems: int               # couldn't be fetched (blocked, login, errors)
    first: int                  # earliest date added
    last: int
    rule: SiteRule

    @property
    def coverage(self) -> float:
        return self.offline / self.items if self.items else 0.0


def site_stats(ctx, limit: int = 0) -> List[SiteStats]:
    """Every site in your archive with its numbers, most items first."""
    rows = ctx.storage.conn.execute(
        """SELECT b.domain d, COUNT(*) n, SUM(CASE WHEN a.bookmark_id IS NULL THEN 0 ELSE 1 END) off,
                  SUM(b.is_dead) dead, MIN(b.date_added) first, MAX(b.date_added) last,
                  SUM(CASE WHEN f.status IN ('blocked','login','error','unreachable',
                                             'timeout','busy') THEN 1 ELSE 0 END) prob
           FROM bookmarks b
           LEFT JOIN archives a ON a.bookmark_id = b.id
           LEFT JOIN fetch_log f ON f.bookmark_id = b.id
           WHERE b.domain IS NOT NULL AND b.domain != ''
           GROUP BY b.domain ORDER BY n DESC, d""" + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    rules = SiteRules(ctx.storage, getattr(ctx.config.settings, "allow_private_addresses", False))
    return [SiteStats(r["d"], r["n"], r["off"] or 0, r["dead"] or 0, r["prob"] or 0,
                      r["first"] or 0, r["last"] or 0, rules.for_domain(r["d"]))
            for r in rows]
