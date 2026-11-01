"""Snapshots for Nawishtar's Reading folder.

Nawishtar reads `~/Nawishtar Reading` (and any folder you add, including
sub-folders) and never changes it. For a saved page it reads the page's own
tags: og:title, og:url / canonical, author, og:site_name,
article:published_time, and chronos:archived — the date Chronos kept it, which
becomes the "accessed" date of the citation. Its passages are the page's
paragraphs, numbered, so a quote cites "para. 3".

So each snapshot here is a clean page:
- those tags in <head>, a SingleFile-style comment with the address and date;
- in <body> only the title and the item's own paragraphs, one <p> each —
  no byline or Chronos furniture, which would shift every paragraph number and
  be quoted as if the author wrote it;
- beside it, `<same name>.chronos.json` with the CSL citation, tags, and *your*
  quotes and takeaways (Nawishtar ignores .json files; it's there for tools
  that read Chronos's notes, and for you).

File names are stable (`title [chronos-12].html`), so writing again updates a
snapshot instead of adding a second copy.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from .. import __version__
from ..interop import bookmark_to_csl
from . import clean, iso, items, paragraphs, record

DEFAULT_FOLDER = Path.home() / "Nawishtar Reading" / "Chronos"
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def file_stem(rec: Dict) -> str:
    title = _BAD.sub(" ", clean(rec["title"]) or "untitled")
    title = re.sub(r"\s+", " ", title).strip(" .")[:80].rstrip(" .") or "untitled"
    return f"{title} [chronos-{rec['id']}]"


def snapshot_html(rec: Dict, paras: List[str]) -> str:
    a = lambda s: html.escape(clean(s), quote=True)      # noqa: E731
    head = [f"<title>{a(rec['title'])}</title>",
            f'<meta property="og:title" content="{a(rec["title"])}">']
    if rec["url"]:
        head += [f'<meta property="og:url" content="{a(rec["url"])}">',
                 f'<link rel="canonical" href="{a(rec["url"])}">']
    if rec["site"]:
        head.append(f'<meta property="og:site_name" content="{a(rec["site"])}">')
    if rec["author"]:
        head.append(f'<meta name="author" content="{a(rec["author"])}">')
    if rec["published"]:
        head.append(f'<meta property="article:published_time" content="{iso(rec["published"])}">')
    if rec["archived"]:
        head.append(f'<meta name="chronos:archived" content="{iso(rec["archived"])}">')
    if rec["wayback"]:
        head.append(f'<meta name="chronos:wayback" content="{a(rec["wayback"])}">')
    head += [f'<meta name="chronos:id" content="{rec["id"]}">',
             f'<meta name="generator" content="Chronos Archive {__version__}">']
    comment = (f"<!--\n Saved by Chronos Archive {__version__}\n"
               f" url: {(rec['url'] or '').replace('--', '%2D%2D')}\n"
               f" saved date: {iso(rec['archived']) or ''}\n-->")
    body = "\n".join(f'<p dir="auto">{html.escape(p)}</p>' for p in paras)
    return ("<!DOCTYPE html>\n" + comment + "\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            + "\n".join(head) + "\n</head>\n<body>\n<article>\n"
            f'<h1 dir="auto">{html.escape(clean(rec["title"]))}</h1>\n'
            + body + "\n</article>\n</body>\n</html>\n")


def write_reading_folder(ctx, folder=None, ids: Optional[List[int]] = None) -> Dict:
    """Write snapshots of `ids` (or every item) into `folder`.
    Returns {"written": n, "skipped": [(id, why)], "folder": path}."""
    folder = Path(folder) if folder else DEFAULT_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []
    for bm in items(ctx, ids):
        paras = paragraphs(ctx, bm)
        if not paras:
            skipped.append((bm.id, "nothing to read yet — save an offline copy first"))
            continue
        rec = record(ctx, bm)
        stem = file_stem(rec)
        tag = f"[chronos-{bm.id}]"
        for old in folder.iterdir():                     # renamed since last time
            if (old.name.endswith((f"{tag}.html", f"{tag}.chronos.json"))
                    and not old.name.startswith(stem + ".")):
                old.unlink()
        (folder / f"{stem}.html").write_text(snapshot_html(rec, paras), encoding="utf-8")
        side = {"source": "chronos", "format": "chronos-reading/1",
                "csl": bookmark_to_csl(bm, rec["archived"]),
                "tags": rec["tags"], "quotes": rec["quotes"],
                "takeaways": rec["takeaways"]}
        (folder / f"{stem}.chronos.json").write_text(
            json.dumps(side, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
    return {"written": written, "skipped": skipped, "folder": str(folder)}
