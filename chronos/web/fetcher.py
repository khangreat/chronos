"""Network-touching operations — every one gated by NetworkPolicy.

Nothing here runs unless you've turned on the relevant capability. Fetching is
separated from extraction so the extractor stays a pure, tested function.

`fetch_document` is the one way Chronos downloads something:
- it says what came back (a web page, a PDF, plain text — or something it
  doesn't keep, like an image or a video), never decoding a PDF as text;
- it follows redirects but records where the address led, and refuses any
  redirect into your own computer or network;
- it stops at 25 MB;
- it explains failures in plain words, telling "gone" (404, 410, no such
  address) apart from "refused" (401/403 — often a login wall), "busy" (429)
  and "try later" (5xx, time-outs), so a link isn't called dead just because a
  site turned a robot away.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .. import __version__
from ..net.policy import NetworkPolicy
from .extract import ExtractedPage, extract_content
from .sites import is_private_url

UA = (f"Mozilla/5.0 (compatible; ChronosArchive/{__version__}; "
      "+https://github.com/khangreat/chronos)")
_HEADERS = {"User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,"
                      "text/plain;q=0.8,*/*;q=0.5",
            "Accept-Language": "en,*;q=0.5"}
MAX_BYTES = 25 << 20
KEEP = {"text/html": "html", "application/xhtml+xml": "html", "application/pdf": "pdf",
        "text/plain": "text"}

# status -> (counts as dead?, worth retrying?)
STATUS = {
    "ok": (False, False), "moved": (False, False), "dead": (True, False),
    "unreachable": (True, False), "blocked": (False, False), "login": (False, False),
    "busy": (False, True), "error": (False, True), "timeout": (False, True),
    "not_page": (False, False), "skipped": (False, False), "private": (False, False),
    "too_big": (False, False),
}


def _same(u: str) -> str:
    """An address without the differences that don't matter (scheme, www., /)."""
    u = u.split("://", 1)[-1]
    return (u[4:] if u.startswith("www.") else u).rstrip("/")


class _SafeRedirect(HTTPRedirectHandler):
    """Follow redirects, but never into this computer or the local network
    (unless you've allowed your own network in Settings)."""

    def __init__(self, allow_private: bool = False):
        super().__init__()
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if is_private_url(newurl) and not self.allow_private:
            raise HTTPError(newurl, 403, "redirect to a private address refused",
                            headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class FetchOutcome:
    url: str
    status: str = "ok"               # see STATUS
    code: int = 0
    reason: str = ""
    final_url: str = ""
    kind: str = ""                   # html | pdf | text ("" = nothing kept)
    mime: str = ""
    body: bytes = field(default=b"", repr=False)
    charset: str = "utf-8"

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "moved")

    @property
    def dead(self) -> bool:
        return STATUS.get(self.status, (False, False))[0]

    @property
    def retry(self) -> bool:
        return STATUS.get(self.status, (False, False))[1]

    def text(self) -> str:
        return self.body.decode(self.charset or "utf-8", errors="replace")


def classify_http(code: int) -> Tuple[str, str]:
    if code in (404, 410):
        return "dead", "The page is gone (the site says it no longer exists)."
    if code in (401, 403, 407, 451):
        return "blocked", ("The site refused (it may need you logged in, or turn "
                           "automatic visitors away).")
    if code == 429:
        return "busy", "The site asked Chronos to slow down; it will try later."
    if code >= 500:
        return "error", f"The site had a problem ({code}); worth trying later."
    if code >= 400:
        return "dead", f"The site said this address doesn't work ({code})."
    return "ok", ""


def _classify_error(e: Exception) -> Tuple[str, str]:
    r = getattr(e, "reason", e)
    if isinstance(r, socket.timeout) or isinstance(e, socket.timeout) or "timed out" in str(r):
        return "timeout", "The site didn't answer in time; worth trying later."
    if isinstance(r, socket.gaierror) or "Name or service not known" in str(r) \
            or "getaddrinfo" in str(r) or "nodename nor servname" in str(r):
        return "unreachable", "This address no longer exists (no such site)."
    return "error", f"Couldn't connect ({r})."


class PageFetcher:
    def __init__(self, policy: NetworkPolicy, timeout: int = 20):
        self.policy = policy
        self.timeout = timeout
        self.allow_private = bool(getattr(policy.settings, "allow_private_addresses", False))
        self._opener = build_opener(_SafeRedirect(self.allow_private))

    # -- the one way to download ------------------------------------------- #
    def fetch_document(self, url: str, capability: str = "page_fetch",
                       method: str = "GET", max_bytes: int = MAX_BYTES,
                       extra_kinds: Optional[dict] = None) -> FetchOutcome:
        self.policy.require(capability)
        out = FetchOutcome(url)
        if not url.startswith(("http://", "https://")):
            out.status, out.reason = "skipped", "Not a web address."
            return out
        if is_private_url(url) and not self.allow_private:
            out.status, out.reason = "private", "An address on your own network — never fetched."
            return out
        try:
            req = Request(url, headers=_HEADERS, method=method)
            with self._opener.open(req, timeout=self.timeout) as resp:  # nosec - gated
                out.code = resp.status
                out.final_url = resp.geturl()
                out.mime = (resp.headers.get_content_type() or "").lower()
                out.charset = resp.headers.get_content_charset() or "utf-8"
                if method == "GET":
                    out.kind = {**KEEP, **(extra_kinds or {})}.get(out.mime, "")
                    if not out.kind:
                        out.status = "not_page"
                        out.reason = (f"Not a page Chronos keeps ({out.mime or 'unknown type'}).")
                        return out
                    data = resp.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        out.status, out.kind = "too_big", ""
                        out.reason = f"Larger than {max_bytes >> 20} MB — not saved."
                        return out
                    out.body = data
                if out.final_url and _same(out.final_url) != _same(url):
                    out.status = "moved"
                    out.reason = f"Moved to {out.final_url}"
                return out
        except HTTPError as e:
            out.code = e.code
            out.status, out.reason = classify_http(e.code)
            if "private address" in str(getattr(e, "msg", "")):
                out.status, out.reason = "private", "Redirected into your own network — refused."
            return out
        except (URLError, socket.timeout, ConnectionError, OSError) as e:
            out.status, out.reason = _classify_error(e)
            return out

    # -- older entry points, kept for callers ------------------------------ #
    def fetch(self, url: str) -> ExtractedPage:
        """Fetch + extract. Raises NetworkDisabled if page_fetch isn't enabled."""
        return extract_content(self.fetch_raw(url), url,
                               getattr(self.policy.settings, "prefer_extractor", "auto"))

    def fetch_raw(self, url: str) -> str:
        """The page's HTML text (raises with a plain reason if it can't)."""
        out = self.fetch_document(url)
        if not out.ok:
            raise RuntimeError(out.reason or out.status)
        if out.kind != "html":
            raise RuntimeError(f"Not a web page ({out.mime}).")
        return out.text()

    def check_alive(self, url: str) -> Tuple[bool, int]:
        """(alive, status code). A HEAD first; many sites refuse HEAD, so a
        refusal is re-asked with GET. "Refused" or "busy" isn't "dead"."""
        out = self.check(url)
        return (not out.dead), out.code

    def check(self, url: str) -> FetchOutcome:
        out = self.fetch_document(url, capability="link_check", method="HEAD")
        if out.status in ("blocked", "error", "dead") and out.code in (400, 403, 404, 405, 501) \
                or out.status == "error" and not out.code:
            again = self.fetch_document(url, capability="link_check", method="GET",
                                        max_bytes=64 << 10)
            if again.status in ("not_page", "too_big"):
                again.status, again.reason = "ok", ""
            return again
        return out

    def wayback_url(self, url: str) -> Optional[str]:
        """Return an archived snapshot URL if one exists. Gated by wayback."""
        self.policy.require("wayback")
        import json
        from urllib.parse import quote
        api = f"https://archive.org/wayback/available?url={quote(url, safe='')}"
        try:
            with urlopen(api, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            snap = data.get("archived_snapshots", {}).get("closest", {})
            found = snap.get("url") if snap.get("available") else None
            if found and found.startswith("http://"):
                found = "https://" + found[len("http://"):]
            return found
        except Exception:
            return None
