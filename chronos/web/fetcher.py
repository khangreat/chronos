"""Network-touching operations — every one gated by NetworkPolicy.

Nothing here runs unless the user has explicitly enabled the relevant
capability. Fetching is separated from extraction so the extractor stays a
pure, fully-tested function and this thin layer only adds the (gated) I/O.
"""

from __future__ import annotations

from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..net.policy import NetworkPolicy
from .extract import ExtractedPage, extract_content

_UA = "ChronosArchive/0.2 (+local; privacy-first bookmark manager)"


class PageFetcher:
    def __init__(self, policy: NetworkPolicy, timeout: int = 10):
        self.policy = policy
        self.timeout = timeout

    def fetch(self, url: str) -> ExtractedPage:
        """Fetch + extract. Raises NetworkDisabled if page_fetch isn't enabled."""
        return extract_content(self.fetch_raw(url), url,
                               getattr(self.policy.settings, "prefer_extractor", "auto"))

    def fetch_raw(self, url: str) -> str:
        """Fetch the raw HTML text. Gated by page_fetch."""
        self.policy.require("page_fetch")
        req = Request(url, headers={"User-Agent": _UA})
        with urlopen(req, timeout=self.timeout) as resp:  # nosec - gated + opt-in
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def check_alive(self, url: str) -> Tuple[bool, int]:
        """Return (alive, status_code). Gated by link_check."""
        self.policy.require("link_check")
        req = Request(url, method="HEAD", headers={"User-Agent": _UA})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return True, resp.status
        except HTTPError as e:
            return (e.code < 400), e.code
        except URLError:
            return False, 0

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
