# Chronos Archive

A local-first, private archive of your web life — bookmarks, history, pages you
keep offline, your Reddit / X / Facebook / Mastodon / Bluesky exports, feeds and
videos — on a timeline, searchable, with your quotes and takeaways, and sent on
to Zotero, Nawishtar, Khwānōk and ytman when you want. Nothing leaves your
computer unless you turn networking on.

## Download (Windows)

Get **`Chronos-…-Windows-portable.zip`** from
[Releases](https://github.com/khangreat/chronos/releases), unzip it anywhere, and
double-click **Chronos.exe** in the `Chronos` folder. No installation and no
Python needed. Your archive stays in the `data` folder beside it. (Windows may
say "Windows protected your PC" because the program isn't signed: *More info →
Run anyway*.)

Every push builds the zip on Windows (Actions → *Windows portable*). When `main`
carries a new version number, it is published as a Release automatically —
only after the tests and both programs' self-tests pass on Windows.

From source: `pip install ./vendor/bridgespec . PySide6`, then `chronos gui`.

---

# v0.35.0 "Windows portable"

- **A portable Windows build.** One folder with `Chronos.exe` (the window) and
  `chronos-cli.exe` (the command line, and the helper the browser extension
  talks to). Built and checked on Windows by GitHub Actions.
- **Your archive travels with it.** With `portable.txt` beside the program, the
  archive lives in `data` next to `Chronos.exe`, or in any folder you name on
  the `data=` line. If that place can't be written to, Chronos uses your user
  folder instead. Delete `portable.txt` to always use your user folder.
- **Bringing an earlier archive.** The first start asks, once, whether to copy
  your existing `.chronos_archive` in, keep using it where it is, or start
  empty. Copying leaves the original in place; nothing is ever moved or
  deleted. Until you choose, both programs keep using the earlier archive, so
  it's never split in two.
- **Help, Open data folder** shows where your archive is; About says when it's
  portable.
- **The browser extension works from the portable app**: its helper is
  `chronos-cli.exe extension host` (before, it needed Python installed).
- **Self-test.** `chronos-cli.exe selftest` (and `Chronos.exe --selftest
  report.txt`) checks that this copy works, in a throw-away folder: database,
  search, every export, translations, extension files, feeds, the SVG pictures
  the theme draws with, and opening the window. The build won't publish a copy
  that fails it.
- **An app icon** — a clock with a bookmark ribbon.
- Windows fixes in the tests (paths compared with `/`, files read without
  saying UTF-8).

---

# v0.34.0 "Citations out"

Your items — with your quotes and takeaways — go straight into the tools you
write and read with. Select one or many, then **Items, Send to** (or right-click,
*Send to*):

- **Zotero.** Sends the items into Zotero 7 on this computer, into whatever
  library or collection is selected there (the same door the Zotero browser
  extension uses). Each arrives as the right kind of item — a Reddit/X/Mastodon
  post as a *Forum Post*, a news article as a *Newspaper Article*, a YouTube
  video as a *Video Recording*, otherwise a *Web Page* — with author, site,
  published date, address, the date you accessed it, summary and your tags.
  Your quotes and takeaways become a child note. An Internet Archive copy comes
  along as a link and as `archive_location` in Extra, so styles can print
  "archived at …". Nothing leaves your computer: Chronos only talks to Zotero
  at 127.0.0.1 (any other address is refused before a request is made) and
  ignores the system proxy, so this works with networking off. If Zotero
  isn't open, you're told so. CLI: `chronos zotero <url|id>…`.
- **Nawishtar Reading folder.** Writes a clean snapshot of each item into
  `~/Nawishtar Reading/Chronos` (or a folder you choose), which Nawishtar's
  *Insert, From your library, Reading* lists. It carries exactly the tags
  Nawishtar reads — title, address, author, site, published date and
  `chronos:archived` (when Chronos kept it, cited as the accessed date) — and
  only the item's own paragraphs, so "para. 3" in Nawishtar is the third
  paragraph of the article. Your quotes and takeaways stay *out* of the page
  (they'd be quoted as the author's words); they go in a `.chronos.json` file
  beside it with the citation. Writing again updates a snapshot instead of
  adding a copy. Items with no text yet are skipped and named. CLI:
  `chronos reading [--to FOLDER] [url|id…]`.
- **Khwānōk reading book (EPUB).** The items as one EPUB 3 book, a chapter
  each: title, where it came from (site, author, dates, address, archived
  copy), the text paragraph by paragraph (mixed scripts in the right direction),
  then — set apart — "Your notes in Chronos". Opens in Khwānōk or any e-reader;
  checked with the W3C's EPUBCheck (0 errors, 0 warnings). CLI:
  `chronos epub out.epub [url|id…]`.
- **ytman** moved here too (*Send to, ytman (videos)…*).

Citation exports, fixed:
- **BibTeX** (biblatex `@online`): titles like "Q&A: 50% off #1" are escaped so
  LaTeX compiles them; several authors are joined with `and`; `date` is the
  publication date only when known — the day you bookmarked something is not
  when it was published, so that goes in `urldate`; an archived copy goes in
  `addendum`.
- **RIS**: one `AU` per author, `PY`/`DA` only for a real publication date, the
  archived copy as `L2`.
- **CSL-JSON**: videos are typed `motion_picture`.

---

# v0.33.0 "Save & archive"

Keep pages where they can't disappear — on your disk, and, if you choose, in
the public Internet Archive — and remember where each copy lives.

- **Save to the Internet Archive** (off until you turn it on). Settings,
  *Save pages to the Internet Archive* — it needs the network master switch too,
  and nothing is sent while either is off. Then the reader's ⋯ menu, or Items,
  *Save selected to the Internet Archive*, asks archive.org's Save Page Now to
  capture the page and stores the snapshot address with the item. A batch is
  spaced out (about 21 s apart, 9 s with your own archive.org keys) and says
  roughly how long it will take; if archive.org says "too many saves" Chronos
  stops instead of hammering it. Only real web pages can be saved — items from
  your Reddit/Facebook/X exports never leave your computer.
- **Your archive.org keys are optional.** Paste `access:secret` from
  archive.org/account/s3.php into Settings (or the `CHRONOS_IA_KEYS`
  environment variable) for faster saves tied to your account.
- **archive.today.** The ⋯ menu also opens the newest archive.today copy or its
  save form in your browser — you finish there; Chronos sends nothing itself.
- **Open the archived copy** from the ⋯ menu once one exists. The existing
  Wayback lookup now encodes the address properly (pages with `?a=1&b=2` used
  to find the wrong snapshot) and uses https.
- **Citations carry the copy.** CSL-JSON gets `archive` ("Internet Archive
  Wayback Machine") and `archive_location` (the snapshot), so citation managers
  can print "archived at …".
- **WARC export.** File, *Export offline copies (WARC)…* (or Items for a
  selection; CLI `chronos warc out.warc.gz`) writes your offline copies as a
  standard WARC 1.1 file — the format the Internet Archive and national
  libraries use — openable in ReplayWeb.page or pywb. Each page carries its
  original address, the date you saved it, and a metadata record with your tags,
  quotes and takeaways. Checked with the independent `warcio` reader, digests
  verified.
- CLI: `chronos ia <url-or-id>…` saves to the Internet Archive (with the
  switches on).

---

# Chronos Archive — v0.32.0 "Videos for ytman"

Videos in your archive — whether you bookmarked the video itself or it sits
inside an article or post you saved — become one item each, ready for ytman.

- **One video, one item.** youtube.com/watch?v=, youtu.be, /shorts, /embed,
  /live, m., music., youtube-nocookie and Vimeo (incl. player.vimeo.com) are
  recognised and reduced to one canonical address; Find duplicates merges the
  variants. Start times (t=90, t=1m30s, start=95) are kept, not lost.
- **Videos inside pages.** Saving an offline copy finds the videos the page
  embeds (iframes, og:video) or links to, even URLs written in the text, and
  links them to the page ("embeds" or "links to", with the start time).
  Tools, *Find videos in saved pages* does this for copies you already have,
  offline.
- **In the reader.** A page shows "Videos in this page"; a video shows "Found
  on" with each page and the moment it pointed at. Library gains *Videos*.
- **To ytman.** `youtube_links()` (bridgespec LinkProvider) now returns every
  YouTube video once, including ones found inside pages, plus playlists and any
  YouTube link it used to return. `video_refs()` adds platform, id and every
  page each video was found on with its start time. Tools, *Send all videos to
  ytman…* / Items, *Send videos in selection to ytman…* (a selected page brings
  its videos) write a handoff file; CLI `chronos videos [list|scan|send FILE]`.
  ytman keeps owning playback and transcripts.
- Migration v9: links can carry a detail (the start time); existing
  YouTube/Vimeo bookmarks are marked as videos (data preserved, checked against
  a v0.31 database).

---

# Chronos Archive — v0.31.0 "Selection & AI"

Select one item or many, and work with them together — including with an AI —
without anything leaving your computer unless you choose.

**Selecting.** Ctrl-click and Shift-click in the list, or Ctrl+A. With two or
more selected, a bar shows the count with *Ask AI…*, *Copy for AI* and more.
The same actions are in the new **Items** menu and on right-click, so they work
from the keyboard and with screen readers too.

**Copy for AI / Save for AI** (always available, no network). The selection
becomes one Markdown block, items numbered [1], [2]…: title, link, what it is
and when, how it reached your archive, tags, *your quotes and takeaways* (first,
because they say what mattered to you), then the text — shared fairly within a
size budget so one long article can't crowd out a short post. Paste or attach it
in any AI chat, Claude included.

**Ask AI** (Ctrl+Shift+A). Summarise, compare, list key claims (with which item
each comes from), find connections, translate to English, or ask your own
question. The window says exactly what is sent and where before you ask. The
answer's [1], [2] references are links: click one to open that item in the main
window beside the answer. Keep an answer by copying it, saving it as a file, or
as a takeaway on each item (marked "[AI · task]" so it never passes for your own
words).

**Where the model runs (Settings, AI).** Off by default.
- *On this computer* — Ollama, LM Studio or a llama.cpp server (presets
  included; *Find models* asks the server what it has). Needs only "Use AI".
  Requests to local addresses bypass any system proxy.
- *On another computer* — any OpenAI-compatible service. Needs the network
  master switch, "Use AI" **and** "Allow AI services on other computers"; the
  window says plainly that your selected items will be sent there. A key can be
  set in Settings or in the CHRONOS_AI_KEY environment variable.
No extra libraries: the client is ~100 lines over the standard library.

**Bulk actions** on any selection: add to favourites, add a tag, export just
these (resolving v0.29's "export is always everything"), remove from archive
(with confirmation).

**Fixed:** Settings dropped any setting it didn't show when you pressed OK (now
it updates the existing settings); unchecked checkboxes were nearly invisible on
the dark theme (now outlined, ticked in the accent colour when on); export-only
items no longer show their internal id as a web domain.

Tests run against a real OpenAI-compatible HTTP server on 127.0.0.1 and check
what is actually sent, that nothing is sent when AI is off, that remote services
need all three switches, and that a system proxy never sees local calls (the
last two adversarially verified).

---

# Chronos Archive — v0.30.0 "Exports, read fully"

Every social import now takes the export as you downloaded it — the .zip, the
unzipped folder, or a single file from inside — and reads all of it.

- **Reddit:** the whole export. Your own posts and comments now arrive *with
  their text*, date and subreddit (as a tag like `r/brahui`); link posts link to
  the page they shared; comments link to their thread; saved items and upvotes
  are kept; downvotes, IP logs, messages and account data are not archived.
  Files are recognised by their columns, not just their names, so differences
  between export versions don't matter. Before, only saved_posts.csv was read,
  and those hold just an ID and a link.
- **Bluesky:** the official "Export my data" `.car` file now works — a small
  built-in reader for CAR v1, DAG-CBOR and the repository's key tree, no extra
  libraries. Posts with threads and shared links, and likes.
- **X:** the archive .zip or folder (tweets, multi-part tweets-partN.js, the
  older tweet.js name, likes) in one go.
- **Mastodon:** the archive .zip directly.
- **Facebook:** group posts; and if you picked the HTML version of the download
  (Facebook's default), Chronos now says so and tells you to request JSON,
  instead of importing nothing.
- **Clear refusals:** a wrong or missing file gets a plain message saying what
  to choose, and no longer leaves a phantom "imported package" behind.

Tests build a genuine CAR repository (independent DAG-CBOR encoder, sha2-256
CIDs, a two-level key tree with prefix compression); mutation checks confirm the
reader test fails if prefix handling or subtree walking breaks.

---

# Chronos Archive — v0.29.0 "Everything in reach"

Every way into Chronos, and every tool, is now in the window — and the window
is usable with a keyboard, a screen reader, larger text, or high contrast.

**Before this release** the GUI reached only browser files, feeds and captures.
Reddit, X, Mastodon, Bluesky, Google Takeout, export, duplicates, link checks,
auto-tagging, meaning search and browser-extension setup were command-line only,
and there was no Facebook support at all.

**Getting things in — File, Import (Ctrl+I).** One window, grouped:
- *Browsers on this computer*: every installed browser whose bookmarks or
  history were found, one click each (Firefox, Chrome, Edge, Brave, Vivaldi,
  Opera, Mullvad, Tor). If none are found it says how to export an HTML file.
- *Files*: a bookmarks HTML export, a copied history database.
- *Social accounts*: Reddit, X, **Facebook (new)**, Mastodon, Bluesky.
- *Account packages and captures*: Google Takeout, a folder of captures.
Each row says where to get the file and what to choose, runs in the
background with its own database connection, and shows a ✓ result or a
plain error in place.

**Facebook** ("Download your information", JSON; .zip or folder): your posts,
saved links, and comments. Facebook's export garbles non-English text
(Urdu/Arabic/Brahui arrive as "Ø§Ù„"); Chronos repairs it. A link you shared
becomes its own item, linked from your post. Likes carry nothing to archive and
are skipped. Also `chronos import-facebook`.

**Capturing while browsing — File, Capture from your browser.** The extension
in three steps with buttons (copy files, load in browser, paste ID and Connect;
on Windows Chronos writes the per-user registry entry itself), and a one-click
"Copy bookmarklet".

**Finding things.** A *Library* under the timeline: Favourites, Kinds (posts,
comments, articles, pages, feed items) and Sources (Facebook, Reddit, Firefox…)
with counts. A *Words / Meaning* switch beside search (meaning = the hybrid
semantic search). Export (Ctrl+E) with plain names for all nine formats; Find
duplicates (shows what it will merge and what it keeps); Check links; Tag
everything automatically. Help: keyboard shortcuts (F1) and About, which shows
where your archive is stored.

**Accessibility.**
- Contrast: the faint text colour failed WCAG AA (3.0–3.7:1) and carried real
  information (dates, counts, status). Now ≥4.5:1 on every surface in every
  theme; a test enforces it.
- New *High contrast* theme (all text ≥9:1).
- *Text size* (Settings, or Ctrl+= / Ctrl+- / Ctrl+0) scales the whole interface,
  including the painted list rows.
- Screen readers: icon-only buttons have names (“Add to favourites”, “More
  actions”); list items read as full sentences (title, kind, source, date, tags);
  panes and controls have names and descriptions.
- Keyboard: Alt-key mnemonics on menus, Enter opens the original, F6 / Shift+F6
  move between timeline, list and reader.

**Fixed along the way:** items imported with their own text (a Facebook post)
showed "Not read yet, turn on networking" — the reader now shows the text, and
never suggests fetching for items with no web page. Facebook comments are titled
by their own words. Tall Arabic-script glyphs are no longer clipped in the list.

Guards: every command-line importer must appear in the Import window, and every
theme must pass contrast checks (both adversarially verified).

Known limits: Bluesky's own .car repository download isn't readable yet (JSON
exports are); Facebook likes/reactions aren't imported (no link or text in the
export); export is always the whole archive.

---

# Chronos Archive — v0.28.0 "Design pass"

A full UI/UX pass, done as a designer would: critique, plan, build, then check
the result at several sizes, in both themes, and right-to-left.

**What was wrong:** labels painted black bars inside the reader; six equal
buttons gave the reader a huge minimum width that crushed the timeline and
stream into truncated slivers; body lines ran ~150 characters; unstyled white
scrollbars; engineering words on screen ("month 03", "Capture", "schema v8");
ALL-CAPS labels and dot-joined meta everywhere; provenance, kind and tags never
shown; dead disabled buttons; arrow keys didn't open items.

**What changed:**
- *Hierarchy.* Only the reader is a raised card; timeline and stream sit flat.
  Panes have sane proportions and minimum widths; nothing truncates at 1024px.
- *Reading.* Serif body capped at a ~70-character column with generous leading.
  The text gets priority over related items.
- *Provenance trail* (the one bold element): brass dots under the title tracing
  how the item reached your archive, oldest first, e.g. "Captured from
  m.social, 10 Mar 2026" then "Saved on Reddit, 14 Mar 2026".
- *Plain language.* Bylines are sentences ("Post by @x on m.social, 10 March
  2026"); headings are "March 2026" with a count; sentence case throughout; the
  wordmark is "Chronos" in serif.
- *Actions.* One primary (Open original), a favourite toggle, Quote, Takeaway;
  Fetch appears only when it can act; rarer actions (Save offline copy, Copy
  link) live in a ⋯ menu.
- *Stream rows.* Title, source domain with a kind word (Post, Article, Feed),
  date and tags; a brass rule marks the selection; the timeline highlights the
  period you're viewing. Redundant group headers are hidden.
- *Empty states that direct.* An empty archive shows how to get things in
  (import, account exports, browser capture); an unread page says how to read it.
- *Keyboard.* Arrow keys open items as you move. Ctrl+F / Ctrl+L search, Esc
  clears, Ctrl+O open original, Ctrl+D favourite, Ctrl+Shift+Q quote,
  Ctrl+Shift+T takeaway. Visible focus rings.
- *Robustness.* A palette floor so unstyled dialogs stay dark on Windows; a
  Windows crash avoided (no `%-d` date formats); stream rows mirror correctly in
  RTL with bidi-isolated runs; all new copy goes through i18n (English, Arabic,
  and empty Brahui keys for you to author).

13 design regression tests guard these fixes (two were adversarially verified by
reintroducing the original bugs).

Known gaps: the byline and provenance sentences, and month names in headings,
are still English in other locales (their grammar needs per-language rules).

---

# Chronos Archive — v0.27.0 "Reader: related & authored"

Surfaces the recent backend work where you actually use it — the reader.

- **Related panel.** Under the reader content, a **Related** list shows the most
  similar resources (from the v0.26 TF-IDF/semantic service). Click one to jump
  to it. It's hidden when there's nothing related.
- **Authored counts.** The reader meta line now shows quotes *and* takeaways for
  the current resource (e.g. "3 quote(s) · 1 takeaway(s)").
- **Reindex related** (Tools menu) rebuilds the similarity index after you import
  or capture a batch, then refreshes the current view.

Small, visible, daily-use polish — the semantic/related search is now one glance
away while reading, not just a CLI call.

---

# Chronos Archive — v0.26.0 "Related & semantic search"

Find resources by meaning and surface related ones — layered and pluggable, with
nothing to install by default.

- **Default (zero deps, offline): TF-IDF cosine.** Reuses the multilingual
  tokenizer (whitespace tokens + CJK bigrams, stopword-filtered), so relatedness
  works across your languages. `ctx.related.related(id)` finds similar resources;
  `semantic_search(query)` ranks by meaning.
- **Hybrid.** `hybrid_search(query)` fuses the existing FTS5/BM25 keyword search
  with the TF-IDF ranking via reciprocal-rank fusion — the documented best
  practice, and nearly free since FTS5 was already there.
- **Pluggable embeddings (optional, never auto-installed).** An `EmbeddingBackend`
  seam lets you drop in dense vectors later — a `Model2VecBackend` (numpy-only,
  ~30 MB, multilingual, torch-free) is included but inert unless you
  `pip install model2vec`; sqlite-vec could back it too. Detected at runtime;
  falls back to TF-IDF when absent. Same optional-provider pattern as trafilatura.
- CLI: `chronos related <url|id>`, `chronos semantic <query>`, `chronos hybrid <query>`.

Design note (from a review of 2026 local-search practice): hybrid BM25 + vectors
is the winning pattern, but for short, keyword-heavy text TF-IDF is still
competitive — so it's the honest default, with a real upgrade path to static
embeddings when you want cross-lingual/synonym recall.

---

# Chronos Archive — v0.25.0 "Takeaway"

Completes the four-layer model (ACQUIRED / CAPTURED / DERIVED / AUTHORED) with the
last authored object it was missing.

A **Takeaway** is what you wanted to *retain* from a resource — your one-line
point, the reason it's worth keeping. It is deliberately distinct from a **Quote**
(the source's exact words, for citing) and a **Note** (your longer thoughts).
Migration v8 adds the table.

- `ctx.takeaways.add / for_bookmark / all / update / remove`; CLI
  `chronos takeaway <url|id> "<text>"` (omit text to list).
- In the reader, an **Add takeaway** button sits beside Quote.
- As authored data it's preserved: dedupe/merge **reassigns** takeaways to the
  surviving resource (never dropped), and they're removed only when you remove
  them or delete the resource.

The AUTHORED layer is now complete: favourites, manual tags, notes, and
takeaways — alongside ACQUIRED (resources + acquisitions), CAPTURED (quotes +
archives), and DERIVED (auto-tags + relationships).

---

# Chronos Archive — v0.24.0 "Rich capture metadata"

Finishes the "select a post → best reference" flow end-to-end. Live capture is
now as rich as an archived page.

- The **bookmarklet** and the **browser extension** now read the page's best-ref
  metadata from the DOM — Open Graph, Twitter card, standard `<meta>`, and (in
  the extension) JSON-LD — and include `author`, `site_name`, `description`, and
  `published` in the capture, alongside the specific post permalink and your
  selection.
- **Capture ingest** uses them: the resource is created with a byline, site,
  publish date, and excerpt, and a re-capture fills only the fields that were
  missing (never overwrites better data). So a captured social post emits a
  **complete CSL citation** — `type: post`, author, container-title, issued —
  ready for Nawishtar, instead of a bare title.

Best references now arrive from every path: account exports (structured export
data), archived pages (metadata extracted from stored HTML, v0.23), and live
capture (metadata read from the DOM, this release).

---

# Chronos Archive — v0.23.0 "Mastodon, Bluesky & richer refs"

Two more platform adapters and better references for everything.

- **`chronos import-mastodon <outbox.json | export-folder>`** parses the
  ActivityPub `outbox.json` (your posts) into `social_post` resources with author
  handle (`@user@domain`), text (HTML stripped), timestamp, and **threads rebuilt**
  from `inReplyTo`. If `bookmarks.json` / `likes.json` sit alongside, their status
  URLs become `platform_saved` / `platform_liked` resources.
- **`chronos import-bluesky <records-or-feed.json>`** parses either a
  `listRecords` (`records`) or `getAuthorFeed` (`feed`) JSON export, turns
  `at://` URIs into `bsky.app` URLs, and rebuilds threads from `reply.parent`.
- **Best-ref metadata.** A new extractor reads Open Graph / Twitter-card /
  standard `<meta>` / JSON-LD from a page's HTML (author, site, publish date,
  description). Archiving a page now enriches its resource with that metadata
  where fields are missing — so its emitted CSL citation gains a real author,
  container-title, and date instead of just a title. (The same idea extends to
  live capture: the extension can read a post's metadata for the best possible
  reference.)

Four adapters now share one ingest path (Reddit, X, Mastodon, Bluesky) — plus
Takeout routing. Each new platform stays "a parser + a thin mapping."

---

# Chronos Archive — v0.22.0 "Takeout inspect & route"

The ecosystem story made real: **ingest, then route by ownership**. Point Chronos
at a Google Takeout (a `.zip` or an extracted folder) and it inventories what's
inside, decides who owns each part, ingests its own slice, and hands off the rest.

- **`chronos takeout inspect <path>`** — walks the archive (reads the listing
  only), groups entries by product, and classifies each: browser bookmarks /
  history / saved links / activity → **Chronos**, YouTube → **ytman**, calendar /
  contacts / tasks / fitness / location → **Command Center**, Keep notes →
  **Nawishtar**, and the rest → skip. Prints an ownership table + plan. It
  computes; it does not act.
- **`chronos takeout import <path>`** — ingests the Chronos-owned parts (Chrome
  `Bookmarks.html` today) recording a **DataPackage** (`google_takeout`, SHA-256,
  entity count, retained path) and `imported` provenance, then writes a **handoff
  manifest per other owner** into the outbox (`ytman.json`, `cc.json`,
  `nawishtar.json`) listing exactly which categories and files are theirs. The
  original package is never modified and is retained as the source of truth.
  Re-importing the same Takeout is a no-op.

The handoff manifests are how the ecosystem stays decoupled: Chronos doesn't
reach into ytman or CC — it prepares each app's slice and points at the retained
package, and those apps (or a future `received_from_bridge` step) pick it up.

---

# Chronos Archive — v0.21.0 "Resource emission"

Closes the loop back to Nawishtar: captured posts and threads are emitted as
**structured, citable references** over the shared `bridgespec` contract — not
bare URLs.

- **bridgespec 1.1 (additive).** New `ResourceProvider` protocol + `ResourceRef`
  type (url, title, kind, csl, author, site, relationships). `CONTRACT_VERSION`
  is now `1.1`; `compatible("1.0")` stays true, so existing 1.0 consumers keep
  working. The broker gains `resource_providers()` and `get_resource(url)`.
- **Typed citations.** `bookmark_to_csl` now types by resource kind — a saved
  tweet/reddit post becomes CSL `post`, a news article `article-newspaper` — so
  a bibliography renders them correctly instead of flattening everything to
  `webpage`.
- **Chronos emits structure.** `ChronosProvider.get_resource(url)` returns a
  `ResourceRef` with the resource's kind, typed CSL, and its **relationships** —
  a reply carries `reply_to → parent`, a post carries `reply_to_by → its
  comments`, a thread its members. `resources_by_kind("social_post")` lists them.
  So Nawishtar can insert a captured thread as a reference that keeps its shape,
  and cite a comment together with the post it answered.

This is the payoff of the provenance/kind/relationship work: everything Chronos
captures — browser, feeds, account exports, live capture — is now not just
stored but *offered to the ecosystem* with its structure intact.

---

# Chronos Archive — v0.20.0 "Browser extension"

One-click "Save to Chronos" from the browser, via a WebExtension + a local
native-messaging host. No server, no telemetry — the browser pipes a capture to
a local process that writes straight to your archive.

Setup (one time):
```
chronos extension unpack ./chronos-extension     # copy the extension files out
# load ./chronos-extension as an unpacked extension (chrome://extensions →
# Developer mode → Load unpacked), then copy its ID
chronos extension install --id <EXTENSION_ID>    # register the native host
```
Then click the toolbar button (or right-click → "Save to Chronos") on any post.
It captures the specific post's permalink near your selection, your selection,
and the title, and the host ingests it (kind, `manual_capture` provenance,
quote, auto-tags) exactly like the bookmarklet — but in one click.

Pieces:
- `chronos/extension/webext/` — the MV3 extension (`manifest.json`,
  `background.js`); `background.js` reuses the bookmarklet's permalink logic and
  calls `chrome.runtime.sendNativeMessage`.
- `chronos/extension/native_host.py` — the stdio host (`python -m
  chronos.extension.native_host`); reads length-framed JSON, ingests, replies.
  Survives bad captures without crashing.
- `chronos/extension/install.py` — writes the native-host manifest + launcher to
  the right per-browser/OS location (`chronos extension install`). On Windows it
  prints the one registry command to add.

Firefox works too (`--browser firefox`; the manifest uses `allowed_extensions`).
The native-messaging JSON is the same capture format the bookmarklet and GUI
paste use, so all three front-ends share one ingest path.

---

# Chronos Archive — v0.19.0 "Capture & inbox"

Live capture from the browser — "save *this* post, from *this* page" — without a
server, without telemetry, and (for now) without an extension.

**How the front-end works.** `chronos bookmarklet` prints a zero-install
`javascript:` bookmarklet. Select a post (or open its permalink) and click it:
it finds the specific post's permalink near your selection (best-effort for
X/Reddit), grabs your selection and the page title, and downloads a small
`capture-*.chronos.json`. Then `chronos inbox <your Downloads folder>` ingests
everything. (A GUI "Paste capture" action reads the same JSON from the
clipboard; a native-messaging extension is the future polished path — the ingest
format below is what it will target.)

**What ingest does.** From a capture it creates/updates the resource with the
right **kind** (X `/status/` → `social_post`, Reddit comment vs post detected,
else `webpage`), records a **`manual_capture`** acquisition (with the source page
and author), turns any **selection into a quote**, links the post **`related`**
to the page you found it on, and **auto-tags** it. Full-text searchable
immediately.

Capture format (only `url` required):
```json
{ "url": "...", "title": "...", "text": "...", "selection": "...",
  "author": "...", "site_name": "...", "kind": "social_post",
  "source_page": "...", "tags": ["..."], "captured_at": 1700000000 }
```

`chronos capture <url> [--select TEXT] [--source-page URL] [--tags a,b]` captures
directly from the CLI.

---

# Chronos Archive — v0.18.0 "X archive import"

The second platform adapter — proving the model generalises. An X (Twitter)
account export imports through the same DataPackage → resources → provenance →
relationships machinery, adding only a parser.

- **`chronos import-x tweets.js`** (or `like.js`) parses the archive's
  `window.YTD.<name>.part0 = [ … ];` JS wrapper, then:
  - your tweets become `social_post` resources (method `imported`, source `x`),
    with the tweet text stored (so it's full-text searchable);
  - **threads are rebuilt** — `in_reply_to_status_id_str` becomes a `reply_to`
    relationship, so `ctx.resources.parent(tweet)` / `replies(tweet)` walk a
    self-thread natively;
  - likes become resources with a `platform_liked` acquisition.
- Same DataPackage guarantees as Reddit: SHA-256 recorded, re-importing the same
  file is a no-op, a newer export adds acquisition occurrences.

Two adapters (Reddit, X) now share one ingest path — new platforms (Facebook
DYI, Mastodon, Bluesky, Google Takeout) are a parser plus a thin mapping, not a
mini-app. That was the point.

---

# Chronos Archive — v0.17.0 "Resource kinds & relationships"

The evolution toward the Resource model, done additively (no rename, no rewrite).

- **Resource kind.** Every resource now has a `kind` — `webpage`, `article`,
  `feed_entry`, `social_post`, `social_comment`, `thread`, `image`, `place`,
  `product`, `generic`. Migration v7 adds the column (default `webpage`) and
  backfills feed items to `feed_entry`. Browser imports stay `webpage`; the
  Reddit importer sets `social_post` / `social_comment`. Query with
  `ctx.resources.by_kind(...)`.
- **Relationship graph.** A `relationships` table connects resources:
  `reply_to`, `quotes`, `in_thread`, `related`, `links_to`. So social structure
  is representable — a Reddit post and its saved comments, an X thread, a quoted
  post. The Reddit importer now links a saved comment `reply_to` its submission
  when the post is also in the archive, so `ctx.resources.replies(post)` lists a
  post's saved comments and `ctx.resources.parent(comment)` returns its post.
  Convenience helpers: `parent`, `replies`, `thread_members`, plus generic
  `outgoing`/`incoming`.

This is the keystone for the social-content vision: adapters (Reddit today; X,
Facebook, Mastodon, Bluesky next) normalise into typed resources with
relationships, rather than each becoming a mini-app. `Resource` can emerge as a
thin view over this — no big-bang migration required.

---

# Chronos Archive — v0.16.0 "Provenance & platform import"

Chronos starts becoming the archive of your whole web life, not just bookmarks.
This release adds **provenance** — how a resource entered — and the first
**account-export importer**.

- **Acquisitions.** Every resource can have one or more acquisitions recording
  *how* it arrived: `browser_bookmark`, `browser_history`, `feed_discovered`,
  `manual_capture`, `platform_saved`, `platform_liked`, `imported`,
  `received_from_bridge`. Recording is idempotent per (method, source, package).
  Migration v6 adds the tables and **backfills** every existing bookmark with an
  acquisition inferred from its browser, so nothing lacks provenance on upgrade.
  Browser/HTML imports, feeds, and reader capture now record their acquisition
  automatically. Query with `chronos provenance <method|source>`.
- **Data packages + Reddit import.** `chronos import-reddit saved_posts.csv`
  ingests a Reddit saved-items export: it records a **DataPackage** (provider,
  original filename, SHA-256, entity count, retained path) and creates a resource
  plus a `platform_saved` acquisition per item. Re-importing the same file is a
  no-op; a newer export (different hash) records a fresh acquisition *occurrence*
  on resources that persist — so the chronology of how an item kept reappearing
  is preserved. This is the pattern all future platform importers (Facebook,
  X, Google Takeout) follow: **ingest, normalise, record provenance, then route
  specialist data to the right ecosystem app** (video → ytman, calendar → CC).

Design note: this deliberately does *not* rename Bookmark → Resource in one big
migration. Provenance is the additive keystone; the richer Resource model
(social posts/comments/threads as first-class types) evolves on top of it.

---

# Chronos Archive — v0.15.0 "Auto-tagging & site test"

Adds local, multi-lingual auto-tagging and a much richer site-test harness.

**Auto-tagging.** `chronos tag` (or `ctx.tagging.auto_tag(id)`) derives apt tags
from a page with no dependencies and no ML: a source tag from the site/domain, a
script tag for non-Latin content (arabic, cjk, hebrew, cyrillic), and topical
keyword tags — stopword-filtered whitespace tokens for space-separated languages
(English/French/German/Spanish/Portuguese/Russian/Arabic stopword sets), or
character bigrams for CJK text (which isn't space-separated). Tags merge with any
you set by hand, and every generated tag is retrievable via `by_tag`. On real
pages it produces things like surveillance/renseignement (Le Monde), totp/password
(heise), lula/libertadores (folha), 腾讯/微博 (qq), 童話/イヌ (a Japanese folktale).

**site_test.py — richer, real-use.** Now spans ~25 sites across many languages
(English, Arabic, Urdu, Persian, Japanese, Chinese, Korean, French, German,
Spanish, Portuguese, Russian, Hindi, plus obscure and very-long pages) and runs
the full workflow per page — bookmark → fetch → extract → archive → auto-tag →
search by content → retrieve by tag → quote — then dedupe, export (all formats),
optional link/Wayback check, and removal. It prints the tags generated per page
so you can judge aptness, plus the scripts seen and a distinct-tag count. Same
safety guarantees: isolated temp workspace, size-capped polite fetching,
deleted at the end unless --keep. Edit the SITES list to your own targets.

---

# Chronos Archive — v0.14.0 "RTL & localization"

Adds right-to-left layout and a JSON string-table i18n with English as the base.

- **i18n.** UI strings live in `chronos/gui/locale/*.json`. A missing or empty
  value falls back to English, so a partially translated locale still renders.
  `tr(key)` looks up the active locale; `retranslate()` re-applies strings after
  a live language change (no restart).
- **RTL.** Selecting an RTL locale (Arabic, Brahui, …) flips the whole app layout
  direction (`Qt.RightToLeft`) — the timeline moves to the right, text
  right-aligns. Chosen in Settings → Language.
- **Locales shipped.** `en` (base), `ar` (real Arabic, so RTL is genuinely
  testable), and `brh` (Brahui scaffold — the keys are present with empty values
  for Hammad to author; until filled, Brahui runs RTL-with-English). Brahui
  wording is the author's call, not the tool's.

Add a locale by dropping a new `<code>.json` next to the others; RTL locales are
listed in `i18n.RTL_LOCALES`.

---

# Chronos Archive — v0.13.0 "Removal & site test"

Adds safe removal and a one-command site-test harness.

**Removal.** `RemovalService` deletes a bookmark and its *derived* data safely:
the archive file on disk is removed first, then the row (which cascades tags,
snippets, and the archive row via foreign keys). `purge_orphans()` clears archive
files whose DB row is gone. The core always survives a removal — remaining
bookmarks, the schema, and the search index keep working (tested).

**site_test.py — safe, click-and-run.** Runs the whole flow (bookmark, fetch,
extract, archive offline, search, quote, export, dedupe, optional link/Wayback
check, and removal) against many real sites, then prints a report.

```
python site_test.py                    # built-in diverse site list
python site_test.py --limit 5 --check  # first 5, plus dead-link + Wayback
python site_test.py --url https://…/article --only
python site_test.py --keep --report out.html
```

It is safe on a fresh machine by construction: everything runs in a throwaway
temp workspace (your real Chronos data is never opened), networking is enabled
ONLY inside that workspace, downloads are size-capped (5 MB) and time-limited
with a polite inter-request delay and identifying User-Agent, and the workspace
(including every archived page) is deleted at the end unless you pass --keep. Edit
the SITES list at the top to point at your own targets (e.g. forgottenlanguages,
newyorker, thebalochistanpost, aljazeera, NHK). Install the optional `extract`
extra for cleaner results on ad/JS-heavy pages.

---

# Chronos Archive — v0.12.0 "Archive & validation"

Adds offline full-page archiving and a rigorous real-world validation pass.

**Archive.** `chronos archive` (or the reader's "Archive offline" button) saves a
local snapshot: the raw HTML gzipped on disk (files-as-truth under the archives
dir) plus the extracted readable text in the DB, so a page survives its source
going dead — complementary to the Wayback fallback. Migration v5 adds the
`archives` table (one snapshot per bookmark, re-archiving updates in place,
deletion cascades). Fetching is gated by page_fetch. Resources (images/CSS/JS)
are not inlined — this is a content + source archive, not a pixel-perfect
capture (that would need a browser engine Chronos deliberately avoids); the
extracted text is the readable offline copy.

**Validation.** Two layers:
- In the suite: multi-script extraction stress (Brahui/Arabic RTL, Japanese CJK),
  a 600-paragraph long page, and boilerplate stripping (nav/header/aside/footer/
  script), plus a malformed-HTML no-crash check.
- A real-corpus probe (`tests/validate_real.py`): pulls diverse real pages from
  Mozilla's readability test corpus (RTL, Chinese, Japanese, French, German, and
  large ad-heavy news sites) and runs the full bookmark -> extract -> archive
  flow. Findings: titles recover on every page and all archive offline; main-text
  recovery is strong on article pages and weak on heavily-templated/JS portals —
  which is exactly what the optional `trafilatura` extractor is for. (Live
  arbitrary sites can't be fetched from the build sandbox; run the probe locally
  to validate your own target sites.)

---

# Chronos Archive — v0.11.0 "Shared contracts"

The interop contract moved into a standalone, versioned package: **`bridgespec`**
(zero third-party deps). Chronos, Command Center, Nawishtar, and ytman now speak
one definition of the citation / link / quote contract instead of each
duplicating the shape.

- `bridgespec` defines the protocols (`CitationProvider`, `LinkProvider`,
  `QuoteProvider`), the types (`LinkRef`, `Quotation`), lightweight validators
  (`validate_csl_item`, `validate_quotation`), a `ProviderRegistry` broker, and a
  `CONTRACT_VERSION` with a `compatible()` check.
- `chronos.interop` now implements that contract and re-exports the names, so
  existing imports keep working.
- Command Center acts as the broker: it registers each app's provider in a
  `ProviderRegistry` and routes citations/links/quotes. Apps depend on
  `bridgespec`, never on each other.

Compatibility rule: signatures never change; a new capability is a new Protocol.
Additive changes bump the contract minor and stay backward compatible.

Install `bridgespec` first (it ships alongside), then Chronos.

---

# Chronos Archive — v0.10.0 "Lazy & links"

Removes the last scale bound and adds dead-link checking.

- **Lazy stream** — period views now page in on demand via keyset pagination
  (`(date_added, id)` cursor, so scroll cost is O(page), not O(offset)). Opening
  a 100,000-row period loads the first page in ~80 ms with negligible memory,
  versus ~2.3 s / +84 MB to materialise it eagerly. No row cap. Search results
  stay eager (already bounded). Keyset completeness is adversarially tested with
  timestamp ties — dropping the id tiebreak drops rows at page seams, and the
  test catches it.
- **Dead-link checking** — `chronos check [--wayback]` probes bookmarks (HEAD,
  gated by link_check), marks dead ones, and — if wayback is enabled — records
  the closest Internet Archive snapshot via the availability API
  (`archive.org/wayback/available`). Dead links show a marker in the stream and a
  banner with the archived link in the reader.

Both network features are gated and off by default.

---

# Chronos Archive — v0.9.0 "Curation & export"

Adds interchange export and duplicate curation.

```
chronos export <format> [outfile]
chronos dedupe [--merge]
```

Formats (chosen from current interchange practice):

- Citations — `csl` (CSL-JSON, the modern lingua franca; drops into Pandoc,
  Typst, Zotero), `bibtex` (@online, for LaTeX), `ris` (reference managers).
- Feeds — `opml` (the universal feed-subscription standard; `opml_to_feed_urls`
  reads it back).
- Quotes — `annotations` (W3C Web Annotation Data Model, with a TextQuoteSelector
  and RTL text-direction for Brahui/Arabic), `quotes-md` (Markdown for Nawishtar).
- Bookmarks — `html` (Netscape, re-importable), `json`, `csv`.

Every writer is round-trip tested where possible: Netscape HTML re-imports
through Chronos's own importer with all URLs intact; OPML reads back to the same
feed URLs; CSL/JSON/annotations parse as valid JSON.

Dedupe finds bookmarks whose URLs normalise to the same page (host lowercased,
`www.`/fragment/trailing-slash ignored) — usually the same page saved in several
browsers. Merge keeps one canonical record and folds in every copy's tags,
favourite state, notes, and captured quotes before removing the rest, so nothing
you added is lost.

---

# Chronos Archive — v0.8.0 "GUI wiring"

Makes the recent features reachable from the window, not just the CLI/API:

- **Settings dialog** (Tools → Settings) — the network capability toggles
  (master + page fetch / feeds / link-check / Wayback), theme, and preferred
  extractor. Changes persist and update the live policy immediately: the reader's
  "Fetch content" button and the offline/online status flip without a restart.
- **Feeds** menu — add a feed URL, refresh all feeds.
- **File** menu — import bookmark/HTML/history files via a picker.
- **Captured quotes** viewer (Tools) — lists quotes with their source citation
  and copies a quote formatted with a reference line.
- **Runtime theme switch** — dusk/midnight swap live, including the painted
  stream delegate.

All wiring is headless-testable: `MainWindow.apply_settings()`, the dialogs'
result methods, and the reload path are exercised offscreen.

Efficiency note: "runs well on modest hardware" means lean implementation
(model/view, event-driven, no telemetry) — not reduced features. The full
feature set is present regardless of machine.

---

# Chronos Archive — v0.7.0 "Capture"

Adds quote capture for Nawishtar. Select text in the reader and capture it as a
Snippet; interop then hands Nawishtar the quote together with the source's
CSL-JSON citation, so a block quote and its reference drop in as one unit.

```python
q = chronos.get_quote(snippet_id)
# -> {"quote": "...", "note": "...", "locator": "para 1",
#     "source": { CSL-JSON of the source page }, "source_app": "chronos"}
chronos.list_quotes()   # all captured quotes with their citations
```

In the GUI: select text in the reader, click "Quote selection". Captured quotes
are counted per source. Migration v4 adds the `snippets` table; deleting a
source cascades its snippets. (Image-region capture needs a rendered page, which
Chronos deliberately doesn't embed — that path is the system browser plus a
screenshot tool, out of scope for the no-Chromium design.)

---

# Chronos Archive — v0.6.0 "Feeds"

Adds RSS/Atom feed ingestion. A feed is just another source: its entries become
bookmarks (browser `RSS`), so timeline, search, the reader, and CSL-JSON
citations all work on feed items unchanged.

```
chronos feed add <feed-url>     # subscribe + import current entries
chronos feed list
chronos feed refresh            # re-pull all feeds
```

Parsing uses `feedparser` when installed (`pip install chronos-archive[feeds]`)
and falls back to a stdlib RSS 2.0 / Atom parser otherwise. Fetching is gated by
a dedicated `feeds` network capability, off by default. Verified end-to-end
against a live GitHub Atom feed, and on RSS/Atom fixtures with Brahui (RTL) and
Japanese entries (both remain FTS-searchable).

For best article extraction from ad-heavy, multilingual news sites, install the
optional `extract` extra (`trafilatura`) — its DOM-based main-text detection is
language-agnostic and handles RTL scripts; the builtin extractor remains the
fallback.

---

# Chronos Archive — v0.5.0 "Scale"

Builds on v0.4. The stream now uses a model/view + painted delegate, so it stays
fast at tens of thousands of rows instead of building a widget per row.

Measured (offscreen bench, `tests/bench_scale.py`):

| approach            | rows   | time   | widgets | RSS Δ   |
|---------------------|--------|--------|---------|---------|
| old widget-per-row  | 5,000  | 3.94 s | 20,005  | +111 MB |
| new model/view      | 50,000 | 0.19 s | 5       | +14 MB  |

Per-row: old ~788 µs, new ~3.7 µs — ~200× faster per row, 10× the data, ~1/8 the memory.

Extraction was probed against real, structurally-different sites
(`tests/probe_real_sites.py`): metadata (title/site/date/excerpt via OG tags)
extracts reliably everywhere; body text is clean on article/content pages
(PyPI) but leaks chrome on JS-heavy app shells (GitHub), which is exactly what
the optional trafilatura/readability extractors are for.

A local-first, privacy-first bookmark and history timeline manager. Modular,
headless-testable core with a PySide6 reader GUI on top of the same code.

## Status

Working **core + CLI + PySide6 GUI**. This release is a correctness/scale pass
plus browser-history import — see the changelog below.

## What it imports

Bookmarks from eight browsers plus portable HTML, and now visited-page history:

- Bookmarks — Firefox, Mullvad, Tor · Chrome, Edge, Brave, Vivaldi, Opera · Netscape HTML
- History — Firefox, Chrome, Edge, Brave (visited pages, deduped to latest visit)

History entries carry their own browser label (e.g. `Firefox history`) so they
never collide with bookmarks on the `(browser, url)` key.

```
chronos import                               # sweep auto-detected profiles
chronos import firefox <places.sqlite>
chronos import "firefox history" <places.sqlite>
chronos import "chrome history" <History>
chronos import chrome  <Bookmarks>
chronos import html    <bookmarks.html>
chronos search <query> · year <YYYY> · timeline · stats · gui [dusk|midnight]
```

## v0.4 changelog

Addresses an external review. Fixes are verified by tests that fail when the fix
is reverted (adversarial verification).

- **Threading correctness** — the background fetch worker now builds its own
  SQLite connection on its own thread instead of borrowing the GUI thread's.
  Reverting this reproduces `SQLite objects created in a thread can only be used
  in that same thread`; the regression test catches it.
- **No N+1 tag queries** — reads batch-load tags for a whole page in one query
  (a trace-callback test asserts ≤2 tag queries regardless of row count).
- **SQL-level month filter + pagination** — `by_period(year, month, limit,
  offset)` filters and paginates in SQL; clicking a month no longer loads the
  whole year into Python. The GUI bounds each view to 500 rows and shows a count.
- **Reader HTML escaping** — extracted text, excerpts, titles, and metadata are
  escaped before display; reader labels are plain-text.
- **History import** — Firefox and Chromium visited-page history.

## Known limits / next

- Full list **virtualization** (model/view + delegate) is v0.5 — the current
  custom-widget rows are fine up to the 500-row page cap but not for painting
  tens of thousands at once.
- Tag editor, collections, settings dialog, import UI: still to come.

## Requirements

- **Core / CLI**: Python 3.9+, standard library only. This keeps the headless
  path installable on low-resource and older systems (the floor target).
- **GUI extra** (`pip install chronos-archive[gui]`): current PySide6 (6.11)
  requires **Python 3.10+**. On 3.9 the CLI works; the GUI needs 3.10+.

The package therefore declares `requires-python >=3.9` deliberately — pinning
the whole package to 3.10 would needlessly block CLI-only installs on the exact
old machines Chronos targets. The GUI's own requirement is documented, not forced
onto the headless core.

## Privacy

No network by default (single `NetworkPolicy` chokepoint, off unless explicitly
enabled). No auto-installer. Read-only browser DB access via read-only copies.
Reading uses extracted text in `QTextBrowser` — no embedded Chromium.

## Interop

`chronos.interop` exposes CSL-JSON citations (Nawishtar) and link queries
(ytman). See `INTEGRATION.md`. Note: the shared contract is planned to move into
a neutral package (v0.6) rather than being owned by any one app.

## Tests

```
python -m unittest discover -s tests -p 'test_*.py'
```

42 tests. GUI/threading tests need PySide6; they skip cleanly without it.

## License

MIT.
