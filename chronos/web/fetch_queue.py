"""Fetch everything — politely, site by site, and safely resumable.

`FetchEngine.plan()` looks at the items you chose (all, a selection, one site)
and decides, for each, whether to fetch it and why not: already saved, the
site needs login, never-fetch, your own network, not a web address (export
items), tried recently and refused. `run()` then works through the plan:

- several sites at once, but one request at a time per site, `pace` seconds
  apart (from the site's rule), so no site is hammered;
- "busy" (429) slows that site down and tries again later; "try later"
  answers (5xx, time-outs) are retried twice, then left for next time;
- network work happens on helper threads; everything is written to your
  archive from one place (SQLite connections belong to one thread);
- pause, resume and stop at any point; nothing half-written. A run that was
  stopped simply continues next time, because finished items are skipped.

Modes: "copy" keeps an offline copy (web page, PDF or text); "check" asks
whether the address still works (dead ≠ refused); "metadata" sites (YouTube,
Vimeo) get their title and author from the site's public oEmbed address.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import Counter, OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

from .fetcher import FetchOutcome, PageFetcher
from .sites import SiteRule, SiteRules

STATUS_LABELS = {
    "ok": "saved", "moved": "saved (the address moved)", "dead": "gone",
    "unreachable": "no such site any more", "blocked": "refused by the site",
    "login": "needs login", "busy": "site busy — try later",
    "error": "site error — try later", "timeout": "no answer — try later",
    "not_page": "not a page (image, video, download)", "too_big": "too large",
    "private": "your own network", "skipped": "skipped",
}
SKIP_LABELS = {
    "saved": "already have an offline copy",
    "login": "the site needs login — use the browser extension",
    "skip": "you chose never to fetch the site",
    "private": "addresses on your own network",
    "not_web": "not web addresses (items from your exports)",
    "recent": "tried recently and refused or gone",
    "metadata_done": "already have their title and author",
}
_NO_RETRY_DAYS = 7


@dataclass
class Job:
    bid: int
    url: str
    domain: str
    rule: SiteRule
    kind: str                    # copy | check | metadata
    tries: int = 0


@dataclass
class Plan:
    mode: str
    jobs: List[Job] = field(default_factory=list)
    skipped: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def sites(self) -> int:
        return len({j.domain for j in self.jobs})

    def summary(self) -> str:
        n = len(self.jobs)
        verb = "check" if self.mode == "check" else "fetch"
        lines = [f"{n:,} item{'s' if n != 1 else ''} to {verb} from {self.sites:,} "
                 f"site{'s' if self.sites != 1 else ''}."]
        for why, per in sorted(self.skipped.items(), key=lambda kv: -sum(kv[1].values())):
            total = sum(per.values())
            top = ", ".join(f"{d or '—'} {c:,}" for d, c in per.most_common(3))
            lines.append(f"Skipping {total:,}: {SKIP_LABELS.get(why, why)} ({top}"
                         + (", …" if len(per) > 3 else "") + ")")
        return "\n".join(lines)


@dataclass
class RunResult:
    mode: str
    counts: Counter = field(default_factory=Counter)
    problems: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    stopped: bool = False

    @property
    def done(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        if not self.counts:
            return "Nothing to do." if not self.stopped else "Stopped before starting."
        saved = self.counts["ok"] + self.counts["moved"]
        head = ("Checked" if self.mode == "check" else "Fetched") + f" {self.done:,}"
        if self.mode == "check":
            head += f": {saved:,} still work, {self.counts['dead'] + self.counts['unreachable']:,} gone"
        else:
            head += f": {saved:,} saved"
        lines = [head + (" (stopped — the rest continue next time)." if self.stopped else ".")]
        for st, n in self.counts.most_common():
            if st in ("ok", "moved"):
                continue
            sites = self.problems.get(st, Counter())
            top = ", ".join(f"{d} {c:,}" for d, c in sites.most_common(3))
            lines.append(f"  • {STATUS_LABELS.get(st, st)}: {n:,}" + (f" ({top})" if top else ""))
        return "\n".join(lines)


class FetchEngine:
    def __init__(self, ctx, workers: int = 4, sleep=time.sleep, clock=time.monotonic):
        self.ctx = ctx
        self.workers = max(1, workers)
        self.sleep, self.clock = sleep, clock
        self.rules = SiteRules(ctx.storage, bool(getattr(
            ctx.config.settings, "allow_private_addresses", False)))
        self.fetcher = PageFetcher(ctx.network)

    # ------------------------------------------------------------------ #
    def plan(self, ids: Optional[List[int]] = None, mode: str = "copy",
             domain: Optional[str] = None, again: bool = False) -> Plan:
        st = self.ctx.storage
        if ids is not None:
            items = [b for b in (st.get(i) for i in ids) if b is not None]
        elif domain:
            items = st.bookmarks_by_domain(domain, 10_000_000)
        else:
            items = st.all_bookmarks()
        plan = Plan(mode)
        have = {r[0] for r in st.conn.execute("SELECT bookmark_id FROM archives")}
        logs = {r["bookmark_id"]: r for r in st.conn.execute("SELECT * FROM fetch_log")}
        now = int(time.time())
        seen = set()
        for b in items:
            url = b.url or ""
            d = getattr(b, "domain", None) or ""
            if not url.startswith(("http://", "https://")):
                plan.skipped["not_web"][d] += 1
                continue
            if url in seen:
                continue
            seen.add(url)
            rule = self.rules.for_url(url)
            d = rule.domain or d
            if rule.mode in ("login", "skip", "private"):
                plan.skipped[rule.mode][d] += 1
                continue
            kind = "check" if mode == "check" else (
                "metadata" if rule.mode == "metadata" else "copy")
            if kind == "copy" and b.id in have and not again:
                plan.skipped["saved"][d] += 1
                continue
            if kind == "metadata" and not again and b.byline:
                plan.skipped["metadata_done"][d] += 1
                continue
            log = logs.get(b.id)
            if (log is not None and not again and log["kind"] == kind
                    and log["status"] in ("blocked", "dead", "unreachable", "not_page",
                                          "too_big", "login")
                    and now - int(log["attempted_at"]) < _NO_RETRY_DAYS * 86400):
                plan.skipped["recent"][d] += 1
                continue
            plan.jobs.append(Job(b.id, url, d, rule, kind))
        return plan

    def require(self, mode: str) -> None:
        """Raise NetworkDisabled (with its plain message) if this can't run."""
        self.ctx.network.require("link_check" if mode == "check" else "page_fetch")

    # ------------------------------------------------------------------ #
    def _network(self, job: Job) -> FetchOutcome:
        """The only part that touches the network (runs on helper threads)."""
        if job.kind == "check":
            return self.fetcher.check(job.url)
        if job.kind == "metadata":
            if "vimeo.com" in job.domain:
                api = f"https://vimeo.com/api/oembed.json?url={quote(job.url, safe='')}"
            else:
                api = f"https://www.youtube.com/oembed?url={quote(job.url, safe='')}&format=json"
            out = self.fetcher.fetch_document(api, extra_kinds={"application/json": "json"})
            out.url = job.url
            return out
        return self.fetcher.fetch_document(job.url)

    def _keep(self, job: Job, out: FetchOutcome) -> None:
        """Write one result to the archive (runs on the calling thread)."""
        st = self.ctx.storage
        status, reason = out.status, out.reason
        if job.kind == "copy" and out.ok:
            try:
                kept = self.ctx.archive.keep(job.bid, out, job.rule.extractor)
                if not kept:
                    status, reason = "not_page", "Nothing to keep."
            except Exception as e:
                status, reason = "error", f"Couldn't keep it: {e}"
        elif job.kind == "metadata" and out.ok:
            try:
                meta = json.loads(out.text())
                st.enrich_metadata(job.bid, {
                    "title": meta.get("title"), "author": meta.get("author_name"),
                    "site_name": meta.get("provider_name")})
                b = st.get(job.bid)
                # replace only placeholder titles ("YouTube video <id>", the address)
                placeholder = (not b.title or b.title == b.url
                               or (b.title.split(" video ")[-1] in b.url
                                   and " video " in b.title))
                if meta.get("title") and placeholder:
                    st.conn.execute("UPDATE bookmarks SET title=? WHERE id=?",
                                    (meta["title"], job.bid))
            except (ValueError, AttributeError):
                status, reason = "error", "The site's answer wasn't readable."
        if job.kind == "check" or out.dead:
            st.mark_link_status(job.bid, out.dead, int(time.time()))
            if out.dead and self.ctx.network.is_allowed("wayback"):
                snap = self.fetcher.wayback_url(job.url)
                if snap:
                    st.set_wayback(job.bid, snap)
        st.log_fetch(job.bid, status, job.kind, out.code or None, reason,
                     out.final_url or None, commit=False)
        st.conn.commit()
        out.status, out.reason = status, reason

    # ------------------------------------------------------------------ #
    def run(self, plan: Plan,
            progress: Optional[Callable[[int, int, Job, FetchOutcome], None]] = None,
            should_stop: Callable[[], bool] = lambda: False,
            paused: Callable[[], bool] = lambda: False) -> RunResult:
        result = RunResult(plan.mode)
        if not plan.jobs:
            return result
        self.require(plan.mode)
        per: "OrderedDict[str, deque]" = OrderedDict()
        for j in plan.jobs:
            per.setdefault(j.domain, deque()).append(j)
        pace = {d: q[0].rule.pace for d, q in per.items()}
        next_at = defaultdict(float)
        busy = set()
        lock = threading.Lock()
        results: "queue.Queue" = queue.Queue()
        total = len(plan.jobs)
        remaining = [total]                 # jobs not yet finished (incl. retries)
        stop = threading.Event()

        def take() -> Optional[Job]:
            with lock:
                now = self.clock()
                for d in list(per):
                    q = per[d]
                    if not q:
                        del per[d]
                        continue
                    if d in busy or next_at[d] > now:
                        continue
                    busy.add(d)
                    next_at[d] = now + pace[d]
                    return q.popleft()
            return None

        def worker():
            while not stop.is_set():
                if paused():
                    self.sleep(0.2)
                    continue
                job = take()
                if job is None:
                    with lock:
                        if not per and remaining[0] <= 0:
                            return
                        empty = not per
                    if empty:
                        self.sleep(0.05)
                        with lock:
                            if remaining[0] <= 0:
                                return
                        continue
                    self.sleep(0.05)
                    continue
                try:
                    out = self._network(job)
                except Exception as e:                    # never lose a worker
                    out = FetchOutcome(job.url, "error", reason=str(e))
                results.put((job, out))

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(min(self.workers, len(per)))]
        for t in threads:
            t.start()
        done = 0
        try:
            while done < total:
                if should_stop():
                    result.stopped = True
                    stop.set()
                    break
                try:
                    job, out = results.get(timeout=0.2)
                except queue.Empty:
                    if not any(t.is_alive() for t in threads):
                        break
                    continue
                with lock:
                    busy.discard(job.domain)
                    if out.status == "busy":                 # slow this site down
                        pace[job.domain] = min(max(pace[job.domain] * 2, 5.0), 120.0)
                    if out.retry and job.tries < 2:
                        job.tries += 1
                        per.setdefault(job.domain, deque()).append(job)
                        next_at[job.domain] = self.clock() + pace[job.domain] * (2 + job.tries)
                        continue
                self._keep(job, out)
                done += 1
                with lock:
                    remaining[0] = total - done
                result.counts[out.status] += 1
                if out.status not in ("ok", "moved"):
                    result.problems[out.status][job.domain] += 1
                if progress:
                    progress(done, total, job, out)
        finally:
            stop.set()
            for t in threads:
                t.join(timeout=30)
            # results that arrived after a stop are still kept (nothing wasted)
            while True:
                try:
                    job, out = results.get_nowait()
                except queue.Empty:
                    break
                self._keep(job, out)
                result.counts[out.status] += 1
        return result

    # ------------------------------------------------------------------ #
    def fetch_one(self, bid: int, again: bool = True) -> FetchOutcome:
        """One item, now (the reader's "save offline copy")."""
        b = self.ctx.storage.get(bid)
        if b is None:
            raise ValueError(f"No item {bid}")
        plan = self.plan([bid], "copy", again=again)
        if not plan.jobs:
            why = next(iter(plan.skipped), "skipped")
            rule = self.rules.for_url(b.url)
            return FetchOutcome(b.url, why if why in ("login", "private") else "skipped",
                                reason=rule.note or SKIP_LABELS.get(why, why))
        self.require("copy")
        job = plan.jobs[0]
        out = self._network(job)
        self._keep(job, out)
        return out
