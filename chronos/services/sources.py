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

from ..importers.base import all_importers


@dataclass
class Source:
    id: str
    group: str            # browsers | social | packages | files
    name: str
    how: str              # where to get the file, what to pick
    pick: str             # "file" | "folder" | "either" | "none"
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


def _browser_run(name):
    def run(ctx, path):
        r = ctx.bookmarks.import_from(name, Path(path) if path else None)
        return f"{r.found:,} found, {r.inserted:,} new in your archive."
    return run


def browser_sources() -> List[Source]:
    """Installed browsers whose bookmarks or history were found on this machine."""
    out = []
    for imp in all_importers():
        if imp.name == "HTML":
            continue
        try:
            where = imp.find_source()
        except Exception:
            where = None
        if where is None:
            continue
        is_hist = "history" in imp.name.lower()
        out.append(Source(
            id=f"browser:{imp.name.lower()}", group="browsers",
            name=(imp.name.replace(" history", "") +
                  (" history" if is_hist else " bookmarks")),
            how=f"Found on this computer: {where}",
            pick="none", file_filter="", run=_browser_run(imp.name),
            found_at=where))
    return out


def file_sources() -> List[Source]:
    pi = lambda ctx: ctx.platform_import  # noqa: E731
    return [
        Source("html", "files", "Bookmarks HTML file",
               "Any browser's “Export bookmarks to HTML” file. Pocket, "
               "Raindrop and most bookmark tools export this format too.",
               "file", "Bookmarks HTML (*.html *.htm)",
               lambda ctx, p: (lambda r: f"{r.found:,} found, {r.inserted:,} new "
                               "in your archive.")(ctx.bookmarks.import_html(Path(p)))),
        Source("history-file", "files", "Browser history file",
               "A copied history database: Firefox places.sqlite, or the Chrome / "
               "Edge / Brave file named History.",
               "file", "History database (*.sqlite *.db History)",
               lambda ctx, p: (lambda r: f"{r.found:,} visits read, {r.inserted:,} "
                               "new in your archive.")(ctx.bookmarks.import_from(
                                   "firefox history" if str(p).endswith(("sqlite", "db"))
                                   else "chrome history", Path(p)))),
        Source("reddit", "social", "Reddit",
               "Request your data in Reddit\u2019s settings (Privacy, request data). "
               "Pick the .zip or its folder: your posts and comments with their text, "
               "saved items, and upvotes. A single CSV such as saved_posts.csv works too.",
               "either", "Reddit export (*.zip *.csv)",
               lambda ctx, p: _summary(pi(ctx).import_reddit(Path(p)), "item")),
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
               "Export from takeout.google.com and pick the .zip or unzipped folder. "
               "Chronos keeps your Chrome bookmarks and prepares YouTube, Calendar "
               "and Keep for ytman, Command Center and Nawishtar.",
               "either", "Takeout (*.zip)",
               lambda ctx, p: (lambda r: "Already imported (same package)."
                               if r.already_imported else
                               f"{r.ingested_bookmarks:,} bookmarks kept. Handed off: "
                               f"{', '.join(r.handoffs) or 'nothing'}.")(
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
    "browsers": "Browsers on this computer",
    "social": "Social accounts",
    "packages": "Account packages and captures",
    "files": "Files",
}
