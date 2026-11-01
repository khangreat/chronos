"""VideoService — videos in your archive, and what links to them, for ytman.

A video becomes one resource at its canonical address (kind "video"), however
many ways it was saved. A page that shows a video records an "embeds" link to it,
a page that only links to it a "links_to" link; either may carry the start time
the page pointed at. ytman owns playback and transcripts — Chronos only says
which videos you have, where you found them, and from what moment.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..core.models import Bookmark
from ..web.video import FoundVideo, Video, parse_video, videos_in_html

_PLATFORM = {"youtube": "YouTube", "vimeo": "Vimeo"}


class VideoService:
    def __init__(self, ctx):
        self.ctx = ctx

    # -- resources ---------------------------------------------------------- #
    def ensure(self, v: Video, title: Optional[str] = None,
               date_added: Optional[int] = None) -> int:
        bm = self.ctx.storage.get_by_url(v.url)
        if bm is not None:
            if bm.kind != "video":
                self.ctx.storage.set_kind(bm.id, "video")
            return bm.id
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=v.url, title=title or f"{_PLATFORM[v.platform]} video {v.video_id}",
            date_added=date_added or int(time.time()), browser="Chronos",
            site_name=_PLATFORM[v.platform], kind="video"))
        return bid

    def scan_page(self, page_id: int, html: str) -> int:
        """Link a saved page to every video it embeds or links to."""
        page = self.ctx.storage.get(page_id)
        if page is None:
            return 0
        own = parse_video(page.url)
        n = 0
        for f in videos_in_html(html, page.url):
            if own and (own.platform, own.video_id) == (f.video.platform, f.video.video_id):
                continue                                # the page *is* this video
            vid = self.ensure(f.video, date_added=page.date_added)
            if vid == page_id:
                continue
            detail = {"start": f.video.start} if f.video.start else None
            self.ctx.storage.add_relationship(
                page_id, vid, "embeds" if f.embedded else "links_to", detail)
            n += 1
        return n

    def scan_saved_pages(self) -> Dict[str, int]:
        """Look through every offline copy for videos (no network)."""
        pages = videos = 0
        before = len(self.all_videos())
        for bm in self.ctx.storage.all_bookmarks():
            if not self.ctx.archive.has_archive(bm.id):
                continue
            html = self.ctx.archive.read_html(bm.id) or ""
            if self.scan_page(bm.id, html):
                pages += 1
        videos = len(self.all_videos()) - before
        return {"pages": pages, "new_videos": max(0, videos)}

    # -- reading ------------------------------------------------------------ #
    def all_videos(self) -> List[Bookmark]:
        return self.ctx.resources.by_kind("video", 100000)

    def found_on(self, video_id: int) -> List[dict]:
        out = []
        for rel, page, detail in self.ctx.storage.relationship_details_in(video_id):
            if rel in ("embeds", "links_to"):
                out.append({"id": page.id, "url": page.url, "title": page.title,
                            "embedded": rel == "embeds",
                            "start": int(detail.get("start", 0) or 0)})
        return out

    def videos_on(self, page_id: int) -> List[Bookmark]:
        return [b for rel, b in self.ctx.resources.outgoing(page_id)
                if rel in ("embeds", "links_to") and b.kind == "video"]

    def refs(self, ids: Optional[List[int]] = None) -> List[dict]:
        """Everything ytman needs about each video (all, or the given ids —
        pages among them contribute the videos they contain)."""
        vids: Dict[int, Bookmark] = {}
        if ids is None:
            vids = {b.id: b for b in self.all_videos()}
        else:
            for i in ids:
                b = self.ctx.storage.get(i)
                if b is None:
                    continue
                if b.kind == "video":
                    vids[b.id] = b
                for v in self.videos_on(i):
                    vids[v.id] = v
        out = []
        for b in vids.values():
            v = parse_video(b.url)
            if v is None:
                continue
            out.append({
                "url": v.url, "platform": v.platform, "video_id": v.video_id,
                "title": b.title, "date_added": b.date_added,
                "favorite": bool(b.is_favorite), "tags": list(b.tags or []),
                "found_on": self.found_on(b.id),
            })
        out.sort(key=lambda r: r["date_added"] or 0, reverse=True)
        return out

    def write_ytman_handoff(self, path, ids: Optional[List[int]] = None) -> int:
        """Write the videos as a handoff file ytman can import."""
        refs = self.refs(ids)
        Path(path).write_text(json.dumps({
            "target": "ytman", "source": "chronos", "format": "chronos-videos/1",
            "created_at": int(time.time()), "videos": refs,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(refs)
