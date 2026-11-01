"""A reading book for Khwānōk (or any e-reader) from the items you pick.

One EPUB 3 file, one chapter per item: its title, where it came from (site,
author, published date, address, when you saved it, the archived copy), the
item's text paragraph by paragraph, and — clearly set apart under "Your notes
in Chronos" — your quotes and takeaways. Mixed scripts read in the right
direction (every paragraph is dir="auto"). Checked with the W3C's EPUBCheck.
"""

from __future__ import annotations

import html
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .. import __version__
from . import clean, is_web, items, paragraphs, record

_CSS = """body { line-height: 1.5; }
h1 { font-size: 1.4em; margin-bottom: 0.3em; }
p.source { font-size: 0.85em; color: #555; margin: 0.1em 0; }
section.mine { border-top: 1px solid #999; margin-top: 2em; padding-top: 0.5em; }
blockquote { margin: 0.5em 1.5em; font-style: italic; }
"""


def _e(s) -> str:
    return html.escape(clean(str(s or "")), quote=True)


def _day(ts) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""


def _xhtml(title: str, body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="und" lang="und">\n'
            f'<head><meta charset="utf-8"/><title>{_e(title)}</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
            f"<body>\n{body}\n</body>\n</html>\n")


def chapter(rec: Dict, paras: List[str]) -> str:
    out = ['<section epub:type="chapter">', f'<h1 dir="auto">{_e(rec["title"])}</h1>']
    line = " · ".join(_e(x) for x in (rec["site"], rec["author"]) if x)
    if rec["published"]:
        line = f"{line} · {_day(rec['published'])}" if line else _day(rec["published"])
    if line:
        out.append(f'<p class="source" dir="auto">{line}</p>')
    if rec["url"]:
        out.append(f'<p class="source"><a href="{_e(rec["url"])}">{_e(rec["url"])}</a></p>')
    saved = f"Saved in Chronos {_day(rec['saved'])}" if rec["saved"] else ""
    if rec["wayback"] and is_web(rec["wayback"]):
        saved += (" · " if saved else "") + \
            f'<a href="{_e(rec["wayback"])}">archived copy</a>'
    if saved:
        out.append(f'<p class="source">{saved}</p>')
    out += [f'<p dir="auto">{_e(p)}</p>' for p in paras]
    if rec["quotes"] or rec["takeaways"]:
        out.append('<section class="mine"><h2>Your notes in Chronos</h2>')
        out += [f'<blockquote><p dir="auto">{_e(q)}</p></blockquote>' for q in rec["quotes"]]
        if rec["takeaways"]:
            out.append("<ul>" + "".join(f'<li dir="auto">{_e(t)}</li>'
                                        for t in rec["takeaways"]) + "</ul>")
        out.append("</section>")
    out.append("</section>")
    return _xhtml(rec["title"], "\n".join(out))


def write_epub(ctx, path, ids: Optional[List[int]] = None,
               title: Optional[str] = None) -> Dict:
    """Write the items as one EPUB. Returns {"chapters": n, "skipped": [(id, why)]}."""
    path = Path(path)
    chapters, skipped = [], []
    for bm in items(ctx, ids):
        paras = paragraphs(ctx, bm)
        if not paras:
            skipped.append((bm.id, "nothing to read yet — save an offline copy first"))
            continue
        rec = record(ctx, bm)
        chapters.append((rec, chapter(rec, paras)))
    if not chapters:
        raise ValueError("None of these items has text to read yet. "
                         "Save offline copies first (the reader's ⋯ menu).")
    now = datetime.now(timezone.utc)
    book = title or f"Chronos reading — {now.strftime('%Y-%m-%d')}"
    toc = "\n".join(f'<li><a href="c{i}.xhtml">{_e(r["title"])}</a></li>'
                    for i, (r, _) in enumerate(chapters, 1))
    nav = _xhtml(book, f'<nav epub:type="toc" id="toc"><h1>{_e(book)}</h1>\n'
                       f"<ol>\n{toc}\n</ol></nav>")
    manifest = "\n".join(
        f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(1, len(chapters) + 1))
    spine = "\n".join(f'<itemref idref="c{i}"/>' for i in range(1, len(chapters) + 1))
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="und">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">urn:uuid:{uuid.uuid4()}</dc:identifier>
<dc:title>{_e(book)}</dc:title>
<dc:language>und</dc:language>
<dc:publisher>Chronos Archive {_e(__version__)}</dc:publisher>
<meta property="dcterms:modified">{now.strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="css" href="style.css" media-type="text/css"/>
{manifest}
</manifest>
<spine>
{spine}
</spine>
</package>
"""
    container = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                 'media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n')
    tmp = path.with_suffix(path.suffix + ".part")
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)            # first, uncompressed
        z.writestr("META-INF/container.xml", container, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", _CSS, zipfile.ZIP_DEFLATED)
        for i, (_, x) in enumerate(chapters, 1):
            z.writestr(f"OEBPS/c{i}.xhtml", x, zipfile.ZIP_DEFLATED)
    tmp.replace(path)
    return {"chapters": len(chapters), "skipped": skipped, "title": book}
