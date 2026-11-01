# Integrating Chronos with your other apps

Chronos is a local-first, autonomous app: SQLite is its own entity truth. Other
apps do **not** reach into its database. They talk to one small, stable surface:
`chronos.interop`. This keeps every app's core intact regardless of the others
(the "core survives every module" rule applies across apps too).

## The model: providers + a broker

- Each app exposes a **provider** implementing a tiny protocol.
- **Command Center** is the **broker**: it holds a registry of providers and
  routes cross-app requests. It never duplicates another app's data.

Chronos's provider is `chronos.interop.ChronosProvider(ctx)`, which implements
two protocols:

```python
from chronos.core.context import ApplicationContext
from chronos.interop import ChronosProvider

ctx = ApplicationContext()          # opens ~/.chronos_archive
chronos = ChronosProvider(ctx)      # register this object in CC's provider table
```

## For Nawishtar — citing a web page (CSL-JSON)

Nawishtar's references logic consumes **CSL-JSON** (the same shape Pandoc,
Zotero, and Typst use), so a Chronos citation drops straight in.

```python
csl = chronos.resolve_citation("https://sqlite.org/fts5.html")
# -> {
#   "type": "webpage",
#   "title": "Understanding FTS5 — SQLite Guide",
#   "container-title": "SQLite Docs",
#   "author": [{"family": "Roe", "given": "Jane"}],
#   "issued":   {"date-parts": [[2024, 5, 1]]},
#   "accessed": {"date-parts": [[2024, 1, 1]]},
#   "URL": "https://sqlite.org/fts5.html",
#   "abstract": "A practical guide to full-text search."
# }
```

- **Offline-first.** If Chronos already fetched the page, the citation is built
  from stored metadata with no network. If it hasn't, and the user has enabled
  `page_fetch`, it fetches once; otherwise it returns a minimal-but-valid
  citation from the bookmark itself (title + URL + accessed date).
- Returns `None` if the URL isn't in Chronos — the broker can then try another
  provider.

## For ytman — pulling YouTube links

ytman owns the rich YouTube entity; Chronos only surfaces the raw links it has
bookmarked or seen in history.

```python
for ref in chronos.youtube_links():
    ytman.ingest(ref.url)           # LinkRef: url, title, site, date_added

# Or any pattern:
chronos.find_links("%github.com%")
```

## The stable contract (duplicate this shape in each app)

```python
class CitationProvider(Protocol):
    def resolve_citation(self, url: str) -> dict | None: ...

class LinkProvider(Protocol):
    def find_links(self, pattern: str) -> list[LinkRef]: ...
```

Keep this surface small and versioned. Add capabilities as *new* methods; don't
change existing signatures, so an older CC keeps working against a newer Chronos.

## Why no embedded browser

Chronos deliberately does **not** bundle QtWebEngine/Chromium to "read" pages.
Reading = extracted article text + metadata (stored, searchable, citable),
shown in a lightweight `QTextBrowser`; "open original" hands the URL to the
system browser. This keeps the floor-machine target (2 GB RAM, no GPU) reachable
and keeps the privacy posture honest — no page renders (and no trackers fire)
unless the user explicitly enables fetching.
