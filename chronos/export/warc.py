"""Write offline copies as a WARC file (ISO 28500, WARC/1.1).

Each page becomes a `resource` record holding its saved HTML at its original
address and archive date, followed by a `metadata` record (application/json)
that refers to it and carries what Chronos knows: title, kind, author, site,
tags, your quotes and takeaways, and any Internet Archive snapshot. A
`warcinfo` record opens the file. Every record is its own gzip member, so the
.warc.gz is readable record by record by standard tools (warcio, pywb,
ReplayWeb.page).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .. import __version__


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(ts) -> str:
    if not ts:
        return _now()
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(data: bytes) -> str:
    return "sha1:" + base64.b32encode(hashlib.sha1(data).digest()).decode()


def _record(rtype: str, payload: bytes, headers: dict) -> tuple:
    rid = f"<urn:uuid:{uuid.uuid4()}>"
    lines = [f"WARC/1.1", f"WARC-Type: {rtype}", f"WARC-Record-ID: {rid}"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    if rtype in ("resource", "response"):
        lines.append(f"WARC-Block-Digest: {_digest(payload)}")
        lines.append(f"WARC-Payload-Digest: {_digest(payload)}")
    lines.append(f"Content-Length: {len(payload)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    return rid, gzip.compress(head + payload + b"\r\n\r\n")


def write_warc(ctx, path, ids: Optional[List[int]] = None) -> int:
    """Write the offline copies (of `ids`, or all) to `path`. Returns pages written."""
    path = Path(path)
    items = ([ctx.storage.get(i) for i in ids] if ids is not None
             else ctx.storage.all_bookmarks())
    info = (f"software: Chronos {__version__}\r\nformat: WARC File Format 1.1\r\n"
            f"conformsTo: https://iipc.github.io/warc-specifications/specifications/"
            f"warc-format/warc-1.1/\r\ndescription: Offline copies from a Chronos "
            f"archive\r\n").encode()
    n = 0
    with open(path, "wb") as out:
        _, rec = _record("warcinfo", info, {
            "WARC-Date": _now(), "WARC-Filename": path.name,
            "Content-Type": "application/warc-fields"})
        out.write(rec)
        for bm in items:
            if bm is None or not ctx.archive.has_archive(bm.id):
                continue
            html = (ctx.archive.read_html(bm.id) or "").encode("utf-8")
            arec = ctx.storage.get_archive(bm.id)
            archived_at = (arec.get("archived_at") if isinstance(arec, dict)
                           else getattr(arec, "archived_at", None))
            rid, rec = _record("resource", html, {
                "WARC-Target-URI": bm.url, "WARC-Date": _iso(archived_at),
                "Content-Type": "text/html; charset=utf-8"})
            out.write(rec)
            meta = {
                "title": bm.title, "url": bm.url, "kind": bm.kind,
                "author": bm.byline, "site": bm.site_name,
                "published": _iso(bm.published_ts) if bm.published_ts else None,
                "saved": _iso(bm.date_added), "tags": list(bm.tags or []),
                "quotes": [q.quote for q in ctx.snippets.for_bookmark(bm.id)],
                "takeaways": [t.text for t in ctx.takeaways.for_bookmark(bm.id)],
                "internet_archive": bm.wayback_url,
            }
            _, mrec = _record("metadata", json.dumps(meta, ensure_ascii=False).encode(), {
                "WARC-Target-URI": bm.url, "WARC-Date": _iso(archived_at),
                "WARC-Refers-To": rid, "Content-Type": "application/json"})
            out.write(mrec)
            n += 1
    return n
