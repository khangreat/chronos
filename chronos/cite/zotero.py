"""Send items straight into Zotero 7 running on this computer.

Zotero listens on http://127.0.0.1:23119 for its browser connector. Chronos
uses the same door: `GET /connector/ping` to see whether Zotero is open, then
`POST /connector/saveItems` with items in Zotero's own translator format.
They land in whatever library or collection is selected in Zotero, the way a
browser save does.

Nothing leaves your computer: the address must be this computer (anything else
is refused before a request is made) and the system proxy is bypassed.

Each item carries:
- the right Zotero type: a post → Forum Post, a news article → Newspaper
  Article, a video → Video Recording, an image → Artwork, else Web Page;
- title, author(s), site, published date, address, the date you accessed it,
  the summary;
- your tags;
- your quotes and takeaways as a child note;
- the Internet Archive copy (if any) as a link attachment and, in Extra, as the
  CSL variables `archive` / `archive_location`, so citation styles can print it.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from . import clean, items, record

DEFAULT = "http://127.0.0.1:23119"
API_VERSION = "3"
BATCH = 50
_LOCAL = {"127.0.0.1", "localhost", "::1"}


class ZoteroError(RuntimeError):
    """Something a person can act on (open Zotero, update it, …)."""


_TYPE = {"social_post": "forumPost", "social_comment": "forumPost", "thread": "forumPost",
         "article": "newspaperArticle", "video": "videoRecording", "image": "artwork"}
_POST_TYPE = {"social_post": "Post", "social_comment": "Comment", "thread": "Thread"}


def _sql(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _date(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _creators(byline: Optional[str], ctype: str) -> List[Dict]:
    out = []
    for name in [n.strip() for n in (byline or "").replace(" and ", ",").split(",")]:
        if not name:
            continue
        parts = name.split()
        # A handle (@x, u/x) or a one-word name stays whole, as Zotero's own
        # site translators do (fieldMode 1 = single field).
        if len(parts) >= 2 and not name.startswith(("@", "u/", "r/")):
            out.append({"firstName": " ".join(parts[:-1]), "lastName": parts[-1],
                        "creatorType": ctype})
        else:
            out.append({"lastName": name, "creatorType": ctype, "fieldMode": 1})
    return out


def _note(rec: Dict) -> Optional[str]:
    if not rec["quotes"] and not rec["takeaways"]:
        return None
    e = lambda s: html.escape(clean(s)).replace("\n", "<br/>")   # noqa: E731
    parts = ["<h1>From Chronos</h1>"]
    if rec["quotes"]:
        parts.append("<h2>Quotes</h2>")
        parts += [f'<blockquote dir="auto"><p>{e(q)}</p></blockquote>' for q in rec["quotes"]]
    if rec["takeaways"]:
        parts.append("<h2>Takeaways</h2><ul>")
        parts += [f'<li dir="auto">{e(t)}</li>' for t in rec["takeaways"]]
        parts.append("</ul>")
    return "".join(parts)


def to_zotero_item(rec: Dict) -> Dict:
    """One Chronos record → one item in Zotero's translator format."""
    kind = rec["kind"]
    itype = _TYPE.get(kind, "webpage")
    it: Dict = {"itemType": itype, "id": f"chronos-{rec['id']}",
                "title": clean(rec["title"]) or "(untitled)"}
    creators = _creators(rec["author"], "artist" if itype == "artwork" else "author")
    if creators:
        it["creators"] = creators
    site = clean(rec["site"]) if rec["site"] else None
    if site:
        key = {"webpage": "websiteTitle", "forumPost": "forumTitle",
               "newspaperArticle": "publicationTitle",
               "videoRecording": "libraryCatalog"}.get(itype)
        if key:
            it[key] = site
    if itype == "forumPost":
        it["postType"] = _POST_TYPE.get(kind, "Post")
    if rec["url"]:
        it["url"] = rec["url"]
        it["accessDate"] = _sql(rec["archived"] or rec["saved"])
    if rec["published"]:
        it["date"] = _date(rec["published"])
    if rec["excerpt"]:
        it["abstractNote"] = clean(rec["excerpt"])
    it["tags"] = [{"tag": t} for t in rec["tags"]]
    note = _note(rec)
    it["notes"] = [{"note": note}] if note else []
    it["attachments"] = []
    if rec["wayback"]:
        it["extra"] = ("archive: Internet Archive Wayback Machine\n"
                       f"archive_location: {rec['wayback']}")
        it["attachments"].append({"title": "Archived copy (Internet Archive)",
                                  "url": rec["wayback"], "mimeType": "text/html",
                                  "snapshot": False})
    return it


# --------------------------------------------------------------------------- #
# Talking to Zotero
# --------------------------------------------------------------------------- #
def _check_local(base: str) -> str:
    host = (urlsplit(base).hostname or "").lower()
    if host not in _LOCAL:
        raise ValueError("Chronos only sends to Zotero on this computer "
                         f"(127.0.0.1), not to {host or base!r}.")
    return base.rstrip("/")


def _open(req, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def _headers(extra=None) -> Dict[str, str]:
    h = {"X-Zotero-Connector-API-Version": API_VERSION,
         "Zotero-Allowed-Request": "1", "User-Agent": "Chronos-Archive"}
    h.update(extra or {})
    return h


_NOT_RUNNING = ("Zotero isn't running. Open Zotero 7 on this computer and try again. "
                "(Zotero must be the desktop app; the website can't receive items.)")


def ping(policy, base: str = DEFAULT, timeout: float = 3) -> bool:
    """True when Zotero is open on this computer."""
    base = _check_local(base)
    policy.require("local_app")
    try:
        with _open(urllib.request.Request(f"{base}/connector/ping", headers=_headers()),
                   timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _post(base: str, payload: Dict, timeout: float) -> int:
    req = urllib.request.Request(
        f"{base}/connector/saveItems", data=json.dumps(payload).encode("utf-8"),
        headers=_headers({"Content-Type": "application/json"}), method="POST")
    try:
        with _open(req, timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError) as e:
        raise ZoteroError(_NOT_RUNNING) from e


def save_items(zitems: List[Dict], policy, base: str = DEFAULT,
               timeout: float = 60) -> int:
    """Send Zotero-format items in batches. Returns how many were saved."""
    base = _check_local(base)
    policy.require("local_app")
    sent = 0
    for i in range(0, len(zitems), BATCH):
        chunk = zitems[i:i + BATCH]
        payload = {"items": chunk, "sessionID": uuid.uuid4().hex}
        first = next((z.get("url") for z in chunk if z.get("url")), None)
        if first:
            payload["uri"] = first
        code = _post(base, payload, timeout)
        if code == 409:                                   # session id clash: retry once
            payload["sessionID"] = uuid.uuid4().hex
            code = _post(base, payload, timeout)
        if code in (200, 201):
            sent += len(chunk)
            continue
        if code in (400, 404, 501):
            raise ZoteroError("This Zotero is too old to receive items from Chronos. "
                              "Update to Zotero 7 and try again.")
        raise ZoteroError(f"Zotero couldn't save the items (it answered {code}). "
                          f"{sent} were saved before that.")
    return sent


def send_to_zotero(ctx, ids: Optional[List[int]], base: str = DEFAULT) -> int:
    """Send these items (with quotes, takeaways and archived copy) to Zotero."""
    if not ping(ctx.network, base):
        raise ZoteroError(_NOT_RUNNING)
    zitems = [to_zotero_item(record(ctx, b)) for b in items(ctx, ids)]
    return save_items(zitems, ctx.network, base)
