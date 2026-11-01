"""Recognise videos — in a URL, or inside a saved page.

One video has many addresses: youtube.com/watch?v=ID, youtu.be/ID,
/shorts/ID, /embed/ID, /live/ID, m.youtube.com, music.youtube.com,
youtube-nocookie.com, with or without a start time (t=1m30s, start=90).
`parse_video` reduces all of them to one canonical address plus the start time,
so the same video saved five ways is one item, and a link that starts at 1:30
still remembers that.

`videos_in_html` finds the videos a page embeds (iframes, og:video) or links to,
so videos inside articles and posts you saved can be handed to ytman too.
Offline: it reads HTML already on disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlsplit

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
             "youtube-nocookie.com", "gaming.youtube.com"}


@dataclass(frozen=True)
class Video:
    platform: str          # youtube | vimeo
    video_id: str
    url: str               # canonical address
    start: int = 0         # seconds; 0 = from the beginning

    @property
    def url_at_start(self) -> str:
        if not self.start:
            return self.url
        sep = "&" if "?" in self.url else "#"
        return f"{self.url}{sep}t={self.start}" if self.platform == "youtube" \
            else f"{self.url}#t={self.start}s"


def _seconds(value: str) -> int:
    """'90', '90s', '1m30s', '1h2m3s', '01:30' -> seconds."""
    v = (value or "").strip().lower()
    if not v:
        return 0
    if v.isdigit():
        return int(v)
    if ":" in v and all(p.isdigit() for p in v.split(":")):
        total = 0
        for p in v.split(":"):
            total = total * 60 + int(p)
        return total
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", v)
    if not m or not any(m.groups()):
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def parse_video(url: str) -> Optional[Video]:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    q = parse_qs(parts.query)
    frag = parse_qs(parts.fragment) if "=" in parts.fragment else {}
    path = [p for p in parts.path.split("/") if p]

    if host in _YT_HOSTS:
        vid = None
        if host == "youtu.be" and path:
            vid = path[0]
        elif q.get("v"):
            vid = q["v"][0]
        elif len(path) >= 2 and path[0] in ("shorts", "embed", "live", "v", "e"):
            vid = path[1]
        if not vid or not _YT_ID.match(vid):
            return None
        t = (q.get("t") or q.get("start") or frag.get("t") or [""])[0]
        return Video("youtube", vid, f"https://www.youtube.com/watch?v={vid}",
                     _seconds(t))

    if host in ("vimeo.com", "player.vimeo.com"):
        nums = [p for p in path if p.isdigit()]
        if not nums:
            return None
        t = parts.fragment[2:] if parts.fragment.startswith("t=") else ""
        return Video("vimeo", nums[0], f"https://vimeo.com/{nums[0]}", _seconds(t))
    return None


_ATTR = re.compile(
    r"""<(?:iframe|embed|source|a|meta|link)\b[^>]*?"""
    r"""(?:src|href|content|data-src)\s*=\s*["']([^"']+)["']""", re.I)
_BARE = re.compile(r"""https?://(?:www\.|m\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be|"""
                   r"""(?:player\.)?vimeo\.com)/[^\s"'<>)\]]+""", re.I)
_EMBED_TAG = re.compile(r"<(iframe|embed|video)\b", re.I)


@dataclass(frozen=True)
class FoundVideo:
    video: Video
    embedded: bool         # shown in the page (iframe/og:video), not just linked


def videos_in_html(html: str, base_url: str = "") -> List[FoundVideo]:
    """Every distinct video a page embeds or links to, in page order."""
    html = html or ""
    seen, out = {}, []
    for m in _ATTR.finditer(html):
        raw = unescape(m.group(1))
        tag = html[m.start():m.start() + 12].lower()
        embedded = bool(_EMBED_TAG.match(tag)) or "og:video" in m.group(0).lower()
        v = parse_video(urljoin(base_url, raw) if base_url else raw)
        if v:
            key = (v.platform, v.video_id)
            if key not in seen:
                seen[key] = len(out)
                out.append(FoundVideo(v, embedded))
            elif embedded and not out[seen[key]].embedded:
                out[seen[key]] = FoundVideo(out[seen[key]].video, True)
    for m in _BARE.finditer(html):                 # URLs written in the text
        v = parse_video(unescape(m.group(0)))
        if v and (v.platform, v.video_id) not in seen:
            seen[(v.platform, v.video_id)] = len(out)
            out.append(FoundVideo(v, False))
    return out
