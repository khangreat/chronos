"""Source catalogue — every way content gets into Chronos, in one place.

The Import window is built from this list, so a new adapter appears in the GUI
by adding one entry here. Each source says what file to choose and where to get
it, in plain language, and runs through the same services the CLI uses.
Browser sources are detected on this machine; the rest take a file or folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional



@dataclass
class Source:
    id: str
    group: str            # anything | browsers | social | packages | files
    name: str
    how: str              # where to get the file, what to pick
    pick: str             # "file" | "folder" | "either" | "many" | "none"
    file_filter: str
    run: Callable         # (ctx, path|None) -> str summary
    found_at: Optional[Path] = None   # browsers: detected profile path


def _summary(r, noun="item") -> str:
    if getattr(r, "already_imported", False):
        return "Already imported (same file). Nothing new."
    read = f"{r.resources:,} {noun}{'s' if r.resources != 1 else ''} read"
    if r.new_resources > r.resources:
        return (f"{read}, {r.new_resources:,} new in your archive "
                "(including pages they link to).")
    return f"{read}, {r.new_resources:,} new in your archive."


def _profile_run(profile, what):
    def run(ctx, path):
        r = ctx.bookmarks.import_profile(profile, what)
        return f"{r.found:,} found, {r.inserted:,} new in your archive."
    return run


def browser_sources() -> List[Source]:
    """Every browser profile on this computer — bookmarks and history apiece."""
    from ..importers.profiles import discover
    out = []
    try:
        profiles = discover()
    except Exception:
        profiles = []
    for p in profiles:
        for what, f in (("bookmarks", p.bookmarks), ("history", p.history)):
            if f is None:
                continue
            note = (" Close the browser first if it says the file is busy."
                    if what == "history" else "")
            out.append(Source(
                id=f"browser:{p.browser.lower()}:{p.folder.name}:{what}",
                group="browsers", name=f"{p.label} {what}",
                how=f"Found on this computer: {f}.{note}",
                pick="none", file_filter="", run=_profile_run(p, what),
                found_at=f))
    return out


def _anything(ctx, p) -> str:
    paths = p if isinstance(p, (list, tuple)) else [p]
    return ctx.universal.import_paths([Path(x) for x in paths]).text()


ANYTHING = Source(
    "anything", "anything", "Anything you downloaded",
    "A Google Takeout (one .zip, all its parts, or a .tgz), a Reddit, X, Facebook, "
    "Mastodon or Bluesky export, a bookmarks.html or browser history file, a Pocket, "
    "Raindrop, Instapaper or Google Saved list, a OneTab list — or a folder holding "
    "any of these, zipped or not. Chronos works out what each file is and tells you "
    "what it kept and what it left.",
    "many", "Exports and archives (*.zip *.tgz *.gz *.tar *.html *.htm *.json *.csv "
    "*.txt *.js *.car *.sqlite)", _anything)


def file_sources() -> List[Source]:
    pi = lambda ctx: ctx.platform_import  # noqa: E731
    return [
        ANYTHING,
        Source("html", "files", "Bookmarks HTML file",
               "Any browser's “Export bookmarks to HTML” file. Pocket, "
               "Raindrop and most bookmark tools export this format too.",
               "file", "Bookmarks HTML (*.html *.htm)",
               lambda ctx, p: (lambda r: f"{r.found:,} found, {r.inserted:,} new "
                               "in your archive.")(ctx.bookmarks.import_html(Path(p)))),
        Source("history-file", "files", "Browser history file",
               "A copied history file: Firefox places.sqlite, the Chrome / Edge / Brave "
               "file named History, or BrowserHistory.json from Google Takeout.",
               "file", "History (*.sqlite *.db *.json History)",
               lambda ctx, p: ctx.universal.import_paths([Path(p)]).text()),
        Source("reddit", "social", "Reddit",
               "Three ways. Quickest: with the Chronos browser extension (File, Capture "
               "from your browser) in Chrome, Edge or Brave, open reddit.com logged in, "
               "right-click the page and choose “Chronos: bring in my Reddit saved, "
               "upvoted, posts and comments” — the last ~1,000 of each, with their "
               "text. Everything: request your data in Reddit’s settings (Privacy, "
               "Request data; it can take up to 30 days) and pick the .zip here; its saved "
               "items are bare links, so then use “Chronos: fill in titles and text "
               "for my Reddit data download” on reddit.com. Without the extension: "
               "logged in, open reddit.com/user/YOUR-NAME/saved.json?limit=100, save the "
               "page, and bring the .json in with “Anything you downloaded”.",
               "either", "Reddit export (*.zip *.csv *.json)",
               lambda ctx, p: (_anything(ctx, p) if str(p).lower().endswith(".json")
                               else _summary(pi(ctx).import_reddit(Path(p)), "item"))),
        Source("x", "social", "X (Twitter)",
               "Download an archive of your data from X\u2019s settings. Pick the .zip "
               "or its folder for your posts and likes, or tweets.js / like.js from "
               "its data folder.",
               "either", "X archive (*.zip *.js)",
               lambda ctx, p: _summary(pi(ctx).import_x(Path(p)), "item")),
        Source("facebook", "social", "Facebook",
               "Use \u201cDownload your information\u201d in Facebook\u2019s settings and "
               "choose JSON format (not HTML). Pick the .zip or its folder. Your posts, "
               "group posts, saved items and comments are kept; likes carry nothing "
               "to archive.",
               "either", "Facebook export (*.zip *.json)",
               lambda ctx, p: _summary(pi(ctx).import_facebook(Path(p)), "item")),
        Source("mastodon", "social", "Mastodon",
               "Request your archive in Mastodon\u2019s preferences (Import and "
               "export). Pick the .zip or its folder for posts, bookmarks and likes, "
               "or just outbox.json.",
               "either", "Mastodon archive (*.zip *.json)",
               lambda ctx, p: _summary(pi(ctx).import_mastodon(Path(p)), "item")),
        Source("bluesky", "social", "Bluesky",
               "In Bluesky, open Settings, Account, \u201cExport my data\u201d, and pick "
               "the .car file it saves: your posts (with threads and shared links) and "
               "likes. A JSON file of posts also works.",
               "file", "Bluesky export (*.car *.json *.zip)",
               lambda ctx, p: _summary(pi(ctx).import_bluesky(Path(p)), "item")),
        Source("takeout", "packages", "Google Takeout",
               "Export from takeout.google.com (choose JSON for My Activity) and pick the "
               ".zip, the .tgz, or the folder holding all its parts. Chronos keeps your "
               "Chrome bookmarks, reading list and history, Chrome activity, Google "
               "searches and Saved links, and prepares YouTube, Calendar, Maps and Keep "
               "for ytman, Command Center and Nawishtar.",
               "either", "Takeout (*.zip *.tgz *.gz)",
               lambda ctx, p: (lambda r: "Already imported (same package)."
                               if r.already_imported else
                               f"{r.ingested_bookmarks:,} items kept. Prepared for: "
                               f"{', '.join(r.handoffs) or 'nothing else'}.")(
                                   ctx.takeout.import_takeout(Path(p)))),
        Source("inbox", "packages", "Capture folder",
               "A folder of captures saved by the bookmarklet (files ending in "
               ".chronos.json), usually your Downloads folder.",
               "folder", "",
               lambda ctx, p: f"{ctx.capture.ingest_inbox(Path(p)):,} capture(s) added."),
    ]


def all_sources() -> List[Source]:
    return browser_sources() + file_sources()


GROUP_TITLES = {
    "anything": "Bring in anything",
    "browsers": "Browsers on this computer",
    "social": "Social accounts",
    "packages": "Account packages and captures",
    "files": "Files",
}
