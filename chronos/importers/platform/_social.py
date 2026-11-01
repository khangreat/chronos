"""Small shared helpers for the social-export parsers (Mastodon, Bluesky)."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Optional


def strip_html(s: Optional[str]) -> str:
    s = s or ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p\s*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def iso_ts(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(s, fmt).timestamp())
            except ValueError:
                continue
    return None
