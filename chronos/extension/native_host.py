"""Native messaging host — the local endpoint the browser extension talks to.

The browser launches this process and sends capture JSON over stdio; the host
ingests each capture into Chronos and replies. No network, no server, no
telemetry — just the browser piping a message to a local process that writes to
your archive.

Run standalone: `python -m chronos.extension.native_host` (this is what the
native-host manifest's `path` points at).
"""

from __future__ import annotations

import sys

from .messaging import read_message, write_message


def handle(ctx, message: dict) -> dict:
    """Process one message from the extension: capture, ping, reddit_listing, reddit_wanted."""
    if not isinstance(message, dict):
        return {"ok": False, "error": "malformed message"}
    mtype = message.get("type", "capture")
    if mtype == "ping":
        return {"ok": True, "pong": True}
    if mtype == "reddit_listing":
        # one page of reddit.com JSON, read in the browser while logged in
        from ..importers.platform.reddit_listing import parse_listing
        try:
            items = parse_listing(message.get("data"), message.get("role", ""))
            if not items:
                return {"ok": True, "read": 0, "new": 0}
            r = ctx.platform_import.import_reddit_items(
                items, label=f"reddit.com ({message.get('role', 'saved')})")
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "read": r.resources, "new": r.new_resources}
    if mtype == "reddit_wanted":
        # items from Reddit's data download that still have no title or text
        return {"ok": True, "ids": ctx.platform_import.reddit_needing_text()}
    if mtype != "capture":
        return {"ok": False, "error": f"unknown type: {mtype}"}
    from ..services.capture_service import CaptureRecord
    try:
        result = ctx.capture.ingest(CaptureRecord.from_dict(message))
    except Exception as e:  # never crash the host on a bad capture
        return {"ok": False, "error": str(e)}
    return {"ok": True, "kind": result.kind, "id": result.bookmark_id,
            "quoted": result.quoted, "new": result.new_resource}


def run(ctx=None, stdin=None, stdout=None) -> int:
    """Read framed messages until EOF, ingesting each. Handles both one-shot
    (sendNativeMessage) and long-lived (connectNative) extension calls."""
    own = ctx is None
    if ctx is None:
        from ..core.context import ApplicationContext
        ctx = ApplicationContext()
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    try:
        while True:
            msg = read_message(stdin)
            if msg is None:
                break
            write_message(stdout, handle(ctx, msg))
    finally:
        if own:
            ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
