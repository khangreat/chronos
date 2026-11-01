#!/usr/bin/env python3
"""Chronos site test — safe, click-and-run, real-use validation.

Replicates how you actually use Chronos, across many real sites in many
languages, and reports whether pages get aptly tagged. Per site it runs:
bookmark -> fetch -> extract -> archive offline -> auto-tag -> search by content
-> retrieve by tag -> capture a quote. Then across the whole set: dedupe/merge,
export (all formats), optional dead-link/Wayback check, and removal. Finally it
prints a report (including the tags generated per page) and cleans up.

SAFE ON A FRESH MACHINE:
  - Everything runs in a throwaway temp workspace; your real Chronos data is
    never opened or modified.
  - Networking is enabled only inside that isolated workspace.
  - Downloads are size-capped (5 MB) and time-limited, with a polite delay
    between requests and an identifying User-Agent.
  - The workspace (and every archived page) is deleted at the end unless --keep.

Usage:
    python site_test.py                     # the built-in multilingual list
    python site_test.py --limit 8           # first 8 only
    python site_test.py --url https://.../article --only
    python site_test.py --check             # + dead-link & Wayback
    python site_test.py --keep --report out.html
    python site_test.py --delay 2.0         # slower / politer

Tip: install the optional extractor for cleaner text on ad/JS-heavy news:
    pip install "chronos-archive[extract]"
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chronos.core.config import Config, Settings
from chronos.core.context import ApplicationContext
from chronos.core.models import Bookmark
from chronos.web.extract import extract_content

# Real, diverse targets across many languages/scripts. Edit freely - specific
# article URLs extract better than homepages. (lang hints are just for report.)
SITES = [
    ("https://forgottenlanguages.org/", "en-obscure"),
    ("https://www.newyorker.com/", "en-longform"),
    ("https://www.bbc.com/news", "en-news"),
    ("https://www.theguardian.com/international", "en-news"),
    ("https://en.wikipedia.org/wiki/Brahui_language", "en-ref"),
    ("https://news.ycombinator.com/", "en-minimal"),
    ("https://arstechnica.com/", "en-tech"),
    ("https://thebalochistanpost.net/", "bal-RTL"),
    ("https://www.aljazeera.net/", "ar-RTL"),
    ("https://www.bbc.com/arabic", "ar-RTL"),
    ("https://www.bbc.com/urdu", "ur-RTL"),
    ("https://www.bbc.com/persian", "fa-RTL"),
    ("https://www3.nhk.or.jp/news/", "ja-CJK"),
    ("https://www.asahi.com/", "ja-CJK"),
    ("https://zh.wikipedia.org/wiki/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD", "zh-CJK"),
    ("https://www.bbc.com/zhongwen/simp", "zh-CJK"),
    ("https://www.bbc.com/korean", "ko-CJK"),
    ("https://www.lemonde.fr/", "fr"),
    ("https://www.heise.de/", "de"),
    ("https://www.spiegel.de/", "de"),
    ("https://elpais.com/", "es"),
    ("https://www.folha.uol.com.br/", "pt"),
    ("https://www.bbc.com/russian", "ru-Cyr"),
    ("https://www.bbc.com/hindi", "hi-Deva"),
    ("https://en.wikipedia.org/wiki/History_of_writing", "en-long"),
]

UA = "ChronosSiteTest/0.15 (+local respectful bot; one-off validation)"
TIMEOUT = 20
MAX_BYTES = 5 * 1024 * 1024


def script_of(text):
    counts = {"Arabic": 0, "CJK": 0, "Hebrew": 0, "Cyrillic": 0,
              "Devanagari": 0, "Latin": 0}
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            counts["Arabic"] += 1
        elif 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF:
            counts["CJK"] += 1
        elif 0x0590 <= o <= 0x05FF:
            counts["Hebrew"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["Cyrillic"] += 1
        elif 0x0900 <= o <= 0x097F:
            counts["Devanagari"] += 1
        elif ch.isalpha():
            counts["Latin"] += 1
    return max(counts, key=counts.get) if any(counts.values()) else "Latin"


def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=TIMEOUT) as resp:
        status = getattr(resp, "status", 200)
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read(MAX_BYTES)
    return raw.decode(charset, errors="replace"), status


def run(sites, delay, do_check, keep, report_path):
    work = Path(tempfile.mkdtemp(prefix="chronos_sitetest_"))
    cfg = Config(work / "home")
    cfg.save_settings(Settings(
        network_enabled=True, allow_page_fetch=True, allow_feeds=True,
        allow_link_check=True, allow_wayback=True))
    ctx = ApplicationContext(cfg)
    rows = []
    print("\nWorkspace (temporary): %s" % work)
    print("Real-use test across %d site(s). Your data is untouched.\n" % len(sites))
    print("%2s %-24s%13s%5s%7s%10s%11s%5s%5s%5s" % (
        "#", "host", "lang", "stat", "txtKB", "script", "extractor",
        "tags", "find", "tag?"))
    print("-" * 92)

    for i, entry in enumerate(sites):
        url, hint = entry if isinstance(entry, tuple) else (entry, "")
        if i:
            time.sleep(delay)
        host = url.split("/")[2] if "://" in url else url
        row = {"url": url, "host": host, "hint": hint, "ok": False, "tags": []}
        try:
            html, status = fetch(url)
        except Exception as e:
            print("%2d %-24s%13s%5s  %s" % (i + 1, host[:23], hint, "ERR",
                                            type(e).__name__))
            row["error"] = str(e)
            rows.append(row)
            continue

        page = extract_content(html, url)
        bid, _ = ctx.storage.upsert_bookmark(Bookmark(
            url=url, title=page.title or host, date_added=1_700_000_000 + i,
            browser="SiteTest"))
        try:
            ctx.archive.archive_from_html(bid, html, url)
        except Exception:
            pass
        try:
            tags = ctx.tagging.auto_tag(bid)
        except Exception:
            tags = []
        token = next((w for w in page.text.split() if len(w) > 6), "")
        findable = bool(token) and any(
            h.id == bid for h in ctx.search.search(token))
        topical = [t for t in tags if t != row["host"] and
                   t not in ("arabic", "cjk", "hebrew", "cyrillic", "latin")]
        tag_ok = bool(topical) and any(
            h.id == bid for h in ctx.storage.by_tag(topical[0]))
        if page.text.strip():
            try:
                ctx.snippets.capture(bid, page.text.strip()[:120])
            except Exception:
                pass

        row.update(ok=True, status=status, text_kb=len(page.text) / 1024,
                   script=script_of(page.text), extractor=page.extractor,
                   tags=tags, findable=findable, tag_ok=tag_ok)
        rows.append(row)
        print("%2d %-24s%13s%5s%7.1f%10s%11s%5d%5s%5s" % (
            i + 1, host[:23], hint, status, len(page.text) / 1024,
            script_of(page.text), page.extractor, len(tags),
            "Y" if findable else "-", "Y" if tag_ok else "-"))

    print("-" * 92)
    ok = [r for r in rows if r["ok"]]
    scripts = sorted({r["script"] for r in ok})
    print("\nFETCHED %d/%d - scripts: %s - archived %d - quotes %d" % (
        len(ok), len(sites), ", ".join(scripts), ctx.storage.archive_count(),
        len(ctx.snippets.all())))

    print("\nTAGS PER PAGE (are they apt?):")
    for r in ok:
        print("  %-32s %s" % (r["host"][:30], ", ".join(r["tags"]) or "(none)"))
    all_tags = sorted({t for r in ok for t in r["tags"]})
    print("\n%d distinct tags generated across the set." % len(all_tags))

    if ok:
        src = ok[0]["url"]
        ctx.storage.upsert_bookmark(Bookmark(
            url=src.replace("https://", "https://www.") + "/", title="dup",
            date_added=1_700_000_000, browser="SiteTest"))
        groups = ctx.curation.find_duplicate_groups()
        merged = ctx.curation.merge_all()
        print("\ndedupe: %d group(s), merged %d dup(s)" % (len(groups), merged.removed))

    exp = []
    for fmt in ("csl", "bibtex", "ris", "opml", "annotations", "quotes-md",
                "html", "json", "csv"):
        try:
            out = ctx.export.export(fmt)
            exp.append(fmt + ("+" if out.strip() else "0"))
        except Exception:
            exp.append(fmt + "x")
    print("export: " + " ".join(exp))

    if do_check:
        try:
            cr = ctx.links.check_all(use_wayback=True)
            print("link-check: %d checked, %d dead, %d archived" % (
                cr.checked, cr.dead, cr.archived))
        except Exception as e:
            print("link-check: skipped (%s)" % e)

    ids = [b.id for b in ctx.storage.all_bookmarks()]
    rr = ctx.removal.remove_many(ids)
    ctx.storage.upsert_bookmark(Bookmark(
        url="https://after.test/x", title="post-removal", date_added=1,
        browser="SiteTest"))
    core_ok = (ctx.storage.version >= 5 and bool(ctx.search.search("post-removal")))
    print("removal: deleted %d, %d archive file(s), purged %d orphan(s) - "
          "core survives: %s" % (rr.removed, rr.files_deleted,
                                 rr.orphans_purged, core_ok))

    if report_path:
        _write_report(Path(report_path), rows)
        print("\nHTML report: %s" % report_path)

    ctx.close()
    if keep:
        print("\nWorkspace kept at: %s" % work)
    else:
        shutil.rmtree(work, ignore_errors=True)
        print("\nWorkspace deleted. Your device is exactly as before.")


def _write_report(path, rows):
    def td(v):
        return "<td>%.1f</td>" % v if isinstance(v, float) else "<td>%s</td>" % v
    trs = ""
    for r in rows:
        if not r.get("ok"):
            trs += "<tr><td>%s</td><td colspan=7>error</td></tr>" % r["host"]
            continue
        trs += ("<tr>" + td(r["host"]) + td(r["hint"]) + td(r["text_kb"]) +
                td(r["script"]) + td(r["extractor"]) +
                "<td>%s</td>" % ", ".join(r["tags"]) +
                td("yes" if r["findable"] else "-") +
                td("yes" if r.get("tag_ok") else "-") + "</tr>")
    path.write_text(
        "<meta charset='utf-8'><h2>Chronos site test</h2>"
        "<table border=1 cellpadding=5 style='border-collapse:collapse;font:14px sans-serif'>"
        "<tr><th>host<th>lang<th>text KB<th>script<th>extractor<th>tags"
        "<th>find<th>tag find</tr>" + trs + "</table>", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Safe, click-and-run Chronos site test.")
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--report", metavar="PATH")
    args = ap.parse_args()

    extra = [(u, "custom") for u in args.url]
    sites = extra if args.only else (SITES + extra)
    if args.limit:
        sites = sites[:args.limit]
    if not sites:
        print("No sites to test.")
        return 2
    run(sites, args.delay, args.check, args.keep, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
