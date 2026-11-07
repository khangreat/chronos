"""Thin CLI over the Core. Every command builds an ApplicationContext and calls
a service — no business logic lives here. This is the Unix-philosophy surface;
the PySide6 GUI will sit on the same Core.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import List

from . import __codename__, __version__
from .core.context import ApplicationContext


def _bar(n: int, peak: int, width: int = 40) -> str:
    if peak <= 0:
        return ""
    return "#" * max(1, round(n / peak * width))


def cmd_import(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        results = ctx.bookmarks.import_all_available()
        if not results:
            print("No browser profiles found to import from.")
            print("Pass a source explicitly, e.g.:")
            print("  chronos import firefox /path/to/places.sqlite")
            print("  chronos import html /path/to/bookmarks.html")
            return 1
        for r in results:
            print(f"  {r.browser:10s}  found {r.found:5d}  new {r.inserted:5d}")
        return 0

    target = args[0].lower()
    source = Path(args[1]) if len(args) > 1 else None
    if target == "html":
        if source is None:
            print("Usage: chronos import html <file.html>")
            return 2
        r = ctx.bookmarks.import_html(source)
    else:
        r = ctx.bookmarks.import_from(target, source)
    print(f"{r.browser}: found {r.found}, imported {r.inserted} new.")
    return 0


def cmd_search(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos search <query>")
        return 2
    query = " ".join(args)
    results = ctx.search.search(query)
    print(f"Search: {query!r} — {len(results)} result(s)\n")
    for i, b in enumerate(results, 1):
        tags = f"  [{', '.join(b.tags)}]" if b.tags else ""
        print(f"[{i}] {b.title}")
        print(f"    {b.url}")
        print(f"    {b.dt:%Y-%m-%d %H:%M} | {b.browser} | {b.folder_name or '-'}{tags}")
    if results:
        choice = input("\nOpen which number (Enter to skip)? ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            url = results[int(choice) - 1].url
            print(f"Opening: {url}")
            webbrowser.open(url)
    return 0


def cmd_year(ctx: ApplicationContext, args: List[str]) -> int:
    if not args or not args[0].isdigit():
        print("Usage: chronos year <YYYY>")
        return 2
    for b in ctx.bookmarks.by_year(int(args[0])):
        print(f"{b.dt:%Y-%m-%d}  {b.title}  ({b.url})")
    return 0


def cmd_stats(ctx: ApplicationContext, args: List[str]) -> int:
    s = ctx.stats.stats()
    print(f"Total bookmarks: {s.total}\n")
    peak = max((c for _, c in s.by_year), default=0)
    print("By year:")
    for year, c in s.by_year:
        print(f"  {year}: {c:5d}  {_bar(c, peak)}")
    print("\nBy browser:")
    for br, c in s.by_browser:
        print(f"  {br:10s} {c}")
    return 0


def cmd_timeline(ctx: ApplicationContext, args: List[str]) -> int:
    tl = ctx.stats.timeline()
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for year in sorted(tl, reverse=True):
        print(f"\n{year}")
        for m, c in tl[year]:
            print(f"  {months[m]:>3s}  {c:4d}  {'#' * min(c, 50)}")
    return 0


def cmd_help(ctx: ApplicationContext, args: List[str]) -> int:
    print(__doc__)
    print("Commands: " + " | ".join(sorted(COMMANDS)))
    return 0


def cmd_gui(ctx: ApplicationContext, args: List[str]) -> int:
    theme = args[0] if args else "dusk"
    try:
        import PySide6  # noqa: F401  (probe the real dependency up front)
        from .gui.app import run_gui
    except ImportError:
        print("The GUI needs PySide6. Install it with:  pip install PySide6")
        print("(or: pip install chronos-archive[gui])")
        print("The text commands (import/search/year/timeline/stats) work without it.")
        return 1
    # The GUI owns its own context/event loop; close the CLI's first.
    ctx.close()
    return run_gui(theme=theme)


def cmd_feed(ctx: ApplicationContext, args: List[str]) -> int:
    sub = args[0] if args else "list"
    if sub == "list":
        feeds = ctx.storage.list_feeds()
        if not feeds:
            print("No feeds. Subscribe with:  chronos feed add <feed-url>")
            return 0
        for f in feeds:
            print(f"  [{f['id']}] {f['title'] or f['url']}  ({f['url']})")
        return 0
    if sub == "add" and len(args) > 1:
        try:
            r = ctx.feeds.subscribe(args[1])
        except Exception as e:
            print(f"Could not subscribe: {e}")
            print("Feeds need networking enabled (network_enabled + allow_feeds).")
            return 1
        print(f"Subscribed to '{r.title}' — {r.new} new of {r.found} entries "
              f"(parser: {r.parser}).")
        return 0
    if sub == "refresh":
        results = ctx.feeds.refresh_all()
        for r in results:
            print(f"  {r.title}: {r.new} new of {r.found}")
        if not results:
            print("No feeds to refresh (or networking is off).")
        return 0
    print("Usage: chronos feed [list | add <url> | refresh]")
    return 2


def cmd_export(ctx: ApplicationContext, args: List[str]) -> int:
    from .services.export_service import FORMATS
    if not args:
        print("Usage: chronos export <format> [outfile]")
        print("Formats: " + ", ".join(FORMATS))
        return 2
    fmt = args[0].lower()
    if fmt not in FORMATS:
        print(f"Unknown format: {fmt}. Known: {', '.join(FORMATS)}")
        return 2
    if len(args) > 1:
        path = Path(args[1])
        ctx.export.export_to(fmt, path)
        print(f"Wrote {fmt} to {path}")
    else:
        print(ctx.export.export(fmt))
    return 0


def cmd_dedupe(ctx: ApplicationContext, args: List[str]) -> int:
    do_merge = "--merge" in args
    groups = ctx.curation.find_duplicate_groups()
    if not groups:
        print("No duplicate URLs found.")
        return 0
    dupes = sum(len(g) - 1 for g in groups)
    print(f"{len(groups)} duplicate group(s), {dupes} removable record(s).")
    for g in groups[:20]:
        print(f"  {g[0].url}  ({len(g)} copies: "
              f"{', '.join(sorted({b.browser for b in g}))})")
    if do_merge:
        r = ctx.curation.merge_all()
        print(f"Merged {r.groups} group(s); removed {r.removed} duplicate(s).")
    else:
        print("Run with --merge to merge them (tags/favorites/notes/quotes kept).")
    return 0


def cmd_check(ctx: ApplicationContext, args: List[str]) -> int:
    use_wb = "--wayback" in args
    limit = 0
    for a in args:
        if a.isdigit():
            limit = int(a)
    try:
        r = ctx.links.check_all(limit=limit, use_wayback=use_wb)
    except Exception as e:
        print(f"Link check needs networking enabled (network_enabled + "
              f"allow_link_check): {e}")
        return 1
    print(f"Checked {r.checked}: {r.dead} dead"
          + (f", {r.archived} with archive snapshots" if use_wb else "") + ".")
    return 0


def cmd_archive(ctx: ApplicationContext, args: List[str]) -> int:
    limit = next((int(a) for a in args if a.isdigit()), 0)
    targets = ctx.storage.all_bookmarks(limit)
    saved = failed = 0
    for b in targets:
        if ctx.archive.has_archive(b.id):
            continue
        try:
            ctx.archive.archive(b.id)
            saved += 1
        except Exception:
            failed += 1
    print(f"Archived {saved} page(s) offline"
          + (f"; {failed} failed (network off or unreachable)." if failed else "."))
    if failed and not ctx.network.is_allowed("page_fetch"):
        print("Enable networking + page fetch in settings to archive pages.")
    return 0


def cmd_tag(ctx: ApplicationContext, args: List[str]) -> int:
    limit = next((int(a) for a in args if a.isdigit()), 0)
    n = ctx.tagging.auto_tag_all(limit)
    print(f"Auto-tagged {n} bookmark(s).")
    return 0


def cmd_import_reddit(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos import-reddit <export.zip | folder | saved_posts.csv>")
        return 2
    path = Path(args[0])
    if not path.exists():
        print(f"No such file: {path}")
        return 1
    try:
        r = ctx.platform_import.import_reddit(path)
    except ValueError as e:
        print(e); return 1
    print(("Already imported (same export). " if r.already_imported else "") +
          f"Reddit: {r.resources} item(s), {r.new_resources} new, "
          f"{r.acquisitions} acquisition(s).")
    return 0


def cmd_provenance(ctx: ApplicationContext, args: List[str]) -> int:
    if args and args[0] == "packages":
        pkgs = ctx.provenance.packages()
        if not pkgs:
            print("No data packages imported.")
        for p in pkgs:
            print(f"  #{p['id']} {p['provider']} · {p['source_filename']} · "
                  f"{p['entity_count']} entities")
        return 0
    if not args:
        print("Usage: chronos provenance <method|source|packages>")
        print("Methods: browser_bookmark browser_history feed_discovered "
              "manual_capture platform_saved imported")
        return 2
    key = args[0]
    hits = ctx.provenance.by_method(key) or ctx.provenance.by_source(key)
    print(f"{len(hits)} resource(s) with acquisition {key!r}:")
    for b in hits[:40]:
        print(f"  {b.title[:50]:<52} {b.url}")
    return 0


def cmd_import_x(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos import-x <archive.zip | folder | tweets.js | like.js>")
        return 2
    path = Path(args[0])
    if not path.exists():
        print(f"No such file: {path}")
        return 1
    try:
        r = ctx.platform_import.import_x(path)
    except ValueError as e:
        print(e); return 1
    print(("Already imported. " if r.already_imported else "") +
          f"X: {r.resources} item(s), {r.new_resources} new, "
          f"{r.acquisitions} acquisition(s).")
    return 0


def cmd_capture(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos capture <url> [--title T] [--select TEXT] "
              "[--source-page URL] [--tags a,b]")
        return 2
    from .services.capture_service import CaptureRecord
    cap = CaptureRecord(url=args[0])
    i = 1
    while i < len(args) - 1:
        flag, val = args[i], args[i + 1]
        if flag == "--title":
            cap.title = val
        elif flag == "--select":
            cap.selection = val
        elif flag == "--source-page":
            cap.source_page = val
        elif flag == "--tags":
            cap.tags = [t.strip() for t in val.split(",") if t.strip()]
        i += 2
    r = ctx.capture.ingest(cap)
    print(f"Captured as {r.kind} (resource #{r.bookmark_id}"
          + (", quote saved" if r.quoted else "") + ").")
    return 0


def cmd_inbox(ctx: ApplicationContext, args: List[str]) -> int:
    folder = args[0] if args else None
    n = ctx.capture.ingest_inbox(folder)
    where = folder or str(ctx.config.inbox_dir)
    print(f"Ingested {n} capture(s) from {where}.")
    return 0


def cmd_bookmarklet(ctx: ApplicationContext, args: List[str]) -> int:
    from .services.capture_service import bookmarklet
    print("Drag this as a bookmark, or create a bookmark with this URL:\n")
    print(bookmarklet())
    print("\nThen: select a post (or open its permalink), click the bookmarklet,")
    print("and run `chronos inbox <your Downloads folder>` to ingest it.")
    return 0


def cmd_extension(ctx: ApplicationContext, args: List[str]) -> int:
    sub = args[0] if args else "help"
    if sub == "host":
        from .extension.native_host import run
        return run(ctx)
    if sub == "unpack":
        from pathlib import Path as _P
        from .extension.install import unpack_to
        dest = unpack_to(_P(args[1]) if len(args) > 1 else _P.cwd() / "chronos-extension")
        print(f"Extension files copied to {dest}")
        print("Load it: chrome://extensions → Developer mode → Load unpacked → "
              "pick that folder. Then copy its ID.")
        return 0
    if sub == "install":
        ext_id = None
        browser = "chrome"
        i = 1
        while i < len(args):
            if args[i] == "--id" and i + 1 < len(args):
                ext_id = args[i + 1]; i += 2
            elif args[i] == "--browser" and i + 1 < len(args):
                browser = args[i + 1]; i += 2
            else:
                i += 1
        if not ext_id:
            print("Usage: chronos extension install --id <extension-id> "
                  "[--browser chrome|chromium|firefox]")
            return 2
        from .extension.install import install
        paths = install(ext_id, browser)
        print(f"Wrote native host manifest: {paths['manifest']}")
        print(f"Launcher: {paths['launcher']}")
        if paths["needs_registry"]:
            from .extension.install import registry_command
            print("\nWindows: add a registry key so the browser finds it:")
            print("  " + registry_command(paths["manifest"], browser))
        return 0
    print("Usage: chronos extension <unpack [dir] | install --id ID | host>")
    print("Steps: 1) unpack  2) load unpacked in the browser, copy its ID")
    print("       3) install --id <ID>  4) click the toolbar button on a post")
    return 0


def cmd_takeout(ctx: ApplicationContext, args: List[str]) -> int:
    if not args or args[0] not in ("inspect", "import"):
        print("Usage: chronos takeout <inspect|import> <path-to-Takeout.zip-or-folder>")
        return 2
    sub = args[0]
    if len(args) < 2:
        print(f"Usage: chronos takeout {sub} <path>")
        return 2
    path = Path(args[1])
    if not path.exists():
        print(f"No such path: {path}")
        return 1
    if sub == "inspect":
        plan = ctx.takeout.inspect(path)
        owners = {"chronos": "→ Chronos", "ytman": "→ ytman",
                  "cc": "→ Command Center", "nawishtar": "→ Nawishtar",
                  "skip": "  (skip)"}
        print(f"Takeout: {path.name}\n")
        print(f"{'owner':<18}{'category':<32}{'files':>7}{'MB':>9}")
        print("-" * 68)
        for c in plan.categories:
            print(f"{owners.get(c.owner, c.owner):<18}{c.category[:31]:<32}"
                  f"{c.files:>7}{c.bytes/1e6:>9.1f}")
        s = plan.summary()
        print("\nPlan:", ", ".join(f"{k}:{v}" for k, v in sorted(s.items())))
        print("Run `takeout import` to ingest Chronos-owned parts and write "
              "handoffs for the rest.")
        return 0
    # import
    r = ctx.takeout.import_takeout(path)
    if r.already_imported:
        print("This Takeout was already imported (same hash).")
    else:
        print(f"Imported {r.ingested_bookmarks} bookmark(s) into Chronos "
              f"(package #{r.package_id}).")
    for owner, mpath in r.handoffs.items():
        print(f"  handoff for {owner}: {mpath}")
    return 0


def cmd_import_mastodon(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos import-mastodon <outbox.json | export-folder>")
        return 2
    r = ctx.platform_import.import_mastodon(Path(args[0]))
    print(f"Mastodon: {r.resources} post(s), {r.new_resources} new, "
          f"{r.acquisitions} acquisition(s).")
    return 0


def cmd_import_facebook(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos import-facebook <export.zip | export-folder>")
        return 2
    r = ctx.platform_import.import_facebook(Path(args[0]))
    if r.already_imported:
        print("Already imported (same export).")
    else:
        print(f"Facebook: {r.resources} item(s), {r.new_resources} new, "
              f"{r.acquisitions} acquisition(s).")
    return 0


def cmd_import_bluesky(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos import-bluesky <records-or-feed.json>")
        return 2
    r = ctx.platform_import.import_bluesky(Path(args[0]))
    print(f"Bluesky: {r.resources} post(s), {r.new_resources} new, "
          f"{r.acquisitions} acquisition(s).")
    return 0


def cmd_takeaway(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print('Usage: chronos takeaway <url|id> "<text>"   (omit text to list)')
        return 2
    key = args[0]
    bm = (ctx.storage.get(int(key)) if key.isdigit()
          else ctx.storage.get_by_url(key))
    if bm is None:
        print(f"No resource: {key}")
        return 1
    if len(args) < 2:
        tks = ctx.takeaways.for_bookmark(bm.id)
        if not tks:
            print("(no takeaways)")
        for t in tks:
            print(f"  #{t.id} {t.text}")
        return 0
    tid = ctx.takeaways.add(bm.id, " ".join(args[1:]))
    print(f"Takeaway #{tid} saved for {bm.title[:50]}.")
    return 0


def cmd_related(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos related <url|id> [k]")
        return 2
    key = args[0]
    bm = (ctx.storage.get(int(key)) if key.isdigit()
          else ctx.storage.get_by_url(key))
    if bm is None:
        print(f"No resource: {key}")
        return 1
    k = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
    hits = ctx.related.related(bm.id, k)
    print(f"Related to {bm.title[:50]!r} (backend: {ctx.related.backend_name()}):")
    for b, score in hits:
        print(f"  {score:>6.3f}  {b.title[:60]}")
    return 0


def cmd_semantic(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos semantic <query>   |   chronos hybrid <query>")
        return 2
    hits = ctx.related.semantic_search(" ".join(args))
    for b, score in hits:
        print(f"  {score:>6.3f}  {b.title[:60]}  {b.url}")
    return 0


def cmd_hybrid(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos hybrid <query>")
        return 2
    hits = ctx.related.hybrid_search(" ".join(args))
    for b, score in hits:
        print(f"  {score:>6.3f}  {b.title[:60]}  {b.url}")
    return 0


def cmd_videos(ctx: ApplicationContext, args: List[str]) -> int:
    sub = args[0] if args else "list"
    if sub == "scan":
        r = ctx.videos.scan_saved_pages()
        print(f"{r['pages']} page(s) contain videos; {r['new_videos']} new video(s).")
        return 0
    if sub == "send":
        if len(args) < 2:
            print("Usage: chronos videos send <file.json>"); return 2
        n = ctx.videos.write_ytman_handoff(Path(args[1]))
        print(f"{n} video(s) written for ytman to {args[1]}")
        return 0
    for r in ctx.videos.refs():
        where = f"  (on {len(r['found_on'])} page(s))" if r["found_on"] else ""
        print(f"  {r['platform']:<8}{r['video_id']:<14}{r['title'][:50]}{where}")
    return 0


def cmd_ia(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos ia <url|id> ...   save to the Internet Archive"""
    if not args:
        print("Usage: chronos ia <url|id> [more…]"); return 2
    ids = []
    for a in args:
        b = ctx.storage.get(int(a)) if a.isdigit() else ctx.storage.get_by_url(a)
        if b is None:
            print(f"Not in your archive: {a}"); return 1
        ids.append(b.id)
    r = ctx.archive.save_many_to_internet_archive(ids)
    for s in r["saved"]:
        print("  saved", s)
    for _, e in r["failed"]:
        print("  not saved:", e)
    return 0 if not r["failed"] else 1


def cmd_warc(ctx: ApplicationContext, args: List[str]) -> int:
    if not args:
        print("Usage: chronos warc <out.warc.gz>"); return 2
    from .export.warc import write_warc
    print(f"{write_warc(ctx, Path(args[0]))} offline cop(ies) written to {args[0]}")
    return 0


def _ids_from(ctx, args: List[str]):
    """Item ids from ids/URLs given; None (= everything) when none given."""
    if not args:
        return None
    ids = []
    for a in args:
        b = ctx.storage.get(int(a)) if a.isdigit() else ctx.storage.get_by_url(a)
        if b is None:
            raise SystemExit(f"Not in your archive: {a}")
        ids.append(b.id)
    return ids


def cmd_zotero(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos zotero <url|id>...   send items to Zotero on this computer"""
    from .cite.zotero import ZoteroError, send_to_zotero
    if not args:
        print("Usage: chronos zotero <url|id> [more…]"); return 2
    try:
        print(f"Sent {send_to_zotero(ctx, _ids_from(ctx, args))} item(s) to Zotero.")
    except ZoteroError as e:
        print(e); return 1
    return 0


def cmd_reading(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos reading [--to FOLDER] [url|id ...]   snapshots for Nawishtar"""
    from .cite.reading import write_reading_folder
    folder = None
    if args[:1] == ["--to"] and len(args) >= 2:
        folder, args = args[1], args[2:]
    r = write_reading_folder(ctx, folder, _ids_from(ctx, args))
    print(f"{r['written']} snapshot(s) in {r['folder']}"
          + (f"; {len(r['skipped'])} without text skipped" if r["skipped"] else ""))
    return 0


def cmd_epub(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos epub OUT.epub [url|id ...]   a reading book for Khwānōk"""
    from .cite.epub import write_epub
    if not args:
        print("Usage: chronos epub <out.epub> [url|id …]"); return 2
    try:
        r = write_epub(ctx, Path(args[0]), _ids_from(ctx, args[1:]))
    except ValueError as e:
        print(e); return 1
    print(f"{r['chapters']} chapter(s) written to {args[0]}"
          + (f"; {len(r['skipped'])} without text skipped" if r["skipped"] else ""))
    return 0


def cmd_fetch(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos fetch [--check] [--site DOMAIN] [--again] [url|id ...]
    save offline copies (or check links) politely, site by site"""
    from .web.fetch_queue import FetchEngine
    mode = "check" if "--check" in args else "copy"
    again = "--again" in args
    domain = None
    rest = []
    it = iter(args)
    for a in it:
        if a == "--site":
            domain = next(it, None)
        elif a not in ("--check", "--again"):
            rest.append(a)
    eng = FetchEngine(ctx)
    plan = eng.plan(_ids_from(ctx, rest), mode, domain, again)
    print(plan.summary())
    if not plan.jobs:
        return 0
    try:
        eng.require(mode)
    except Exception as e:
        print(e); return 1

    def show(done, total, job, out):
        print(f"[{done}/{total}] {job.domain}: {out.status}"
              + (f" \u2014 {out.reason}" if out.reason and not out.ok else ""), flush=True)
    try:
        r = eng.run(plan, progress=show)
    except KeyboardInterrupt:
        print("Stopped. Run it again to continue."); return 1
    print(r.summary())
    return 0


def cmd_sites(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos sites [N]   your sites: items, offline copies, gone, rule"""
    from .web.sites import MODE_LABELS, site_stats
    n = int(args[0]) if args and args[0].isdigit() else 40
    rows = site_stats(ctx, n)
    print(f"{'site':40} {'items':>7} {'offline':>8} {'gone':>5}  rule")
    for s in rows:
        rule = MODE_LABELS.get(s.rule.mode, s.rule.mode).split(" \u2014")[0]
        print(f"{s.domain[:40]:40} {s.items:>7,} {s.offline:>8,} {s.dead:>5,}  {rule}")
    return 0


def cmd_backup(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos backup [--full FOLDER]   back up now (or everything, as a .zip)"""
    if args[:1] == ["--full"]:
        if len(args) < 2:
            print("Usage: chronos backup --full <folder>"); return 2
        print(f"Full backup written: {ctx.safekeeping.full_backup(args[1])}")
        return 0
    print(f"Backed up: {ctx.safekeeping.backup('manual')}")
    for b in ctx.safekeeping.list()[:8]:
        print(f"  {b.label}")
    return 0


def cmd_restore(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos restore <backup.db|full.zip>   put the archive back (a safety copy first)"""
    if not args:
        print("Usage: chronos restore <backup.db or full .zip>")
        for b in ctx.safekeeping.list()[:10]:
            print(f"  {b.path}    {b.label}")
        return 2
    try:
        safety = ctx.safekeeping.restore(args[0])
    except Exception as e:
        print(f"Couldn't restore: {e}"); return 1
    print(f"Restored. How it was before is kept in {safety}")
    return 0


def cmd_health(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos health [--deep] [--repair]   check (and fix) your archive"""
    r = ctx.safekeeping.check(deep="--deep" in args)
    print(r.text())
    if "--repair" in args and r.repairable:
        print("\n".join(ctx.safekeeping.repair(r)))
    return 0 if r.ok else 1


def cmd_usage(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos usage   what takes space"""
    from .services.safekeeping import size_text
    u = ctx.safekeeping.usage()
    for k in ("database", "journal", "saved_pages", "removed", "backups", "favicons", "free"):
        print(f"{k.replace('_', ' '):12} {size_text(u[k]):>12}")
    return 0


def cmd_compact(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos compact   give back space removed items left behind"""
    from .services.safekeeping import size_text
    print(f"Compacted: {size_text(ctx.safekeeping.compact())} given back.")
    return 0


def cmd_selftest(ctx: ApplicationContext, args: List[str]) -> int:
    """chronos selftest [--gui] [report.txt]   check this copy of Chronos works"""
    from .selftest import run_selftest
    gui = "--gui" in args
    rest = [a for a in args if a != "--gui"]
    return run_selftest(gui=gui, report=rest[0] if rest else None)


COMMANDS = {
    "import": cmd_import, "search": cmd_search, "year": cmd_year,
    "timeline": cmd_timeline, "stats": cmd_stats, "gui": cmd_gui,
    "feed": cmd_feed, "export": cmd_export, "dedupe": cmd_dedupe,
    "check": cmd_check, "archive": cmd_archive, "tag": cmd_tag,
    "import-reddit": cmd_import_reddit, "import-x": cmd_import_x,
    "import-mastodon": cmd_import_mastodon,
    "import-facebook": cmd_import_facebook, "import-bluesky": cmd_import_bluesky,
    "capture": cmd_capture, "inbox": cmd_inbox, "bookmarklet": cmd_bookmarklet,
    "extension": cmd_extension, "takeout": cmd_takeout, "takeaway": cmd_takeaway,
    "videos": cmd_videos, "ia": cmd_ia, "zotero": cmd_zotero,
    "reading": cmd_reading, "epub": cmd_epub, "selftest": cmd_selftest,
    "fetch": cmd_fetch, "sites": cmd_sites, "backup": cmd_backup, "restore": cmd_restore,
    "health": cmd_health, "usage": cmd_usage, "compact": cmd_compact, "warc": cmd_warc, "related": cmd_related, "semantic": cmd_semantic, "hybrid": cmd_hybrid,
    "provenance": cmd_provenance, "help": cmd_help,
}


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(f"Chronos Archive {__version__} \"{__codename__}\"")
        return cmd_help(None, [])  # type: ignore[arg-type]
    cmd, rest = argv[0], argv[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}")
        return 2
    with ApplicationContext() as ctx:
        return fn(ctx, rest)


if __name__ == "__main__":
    raise SystemExit(main())
