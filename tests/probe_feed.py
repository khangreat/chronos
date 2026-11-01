import sys, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chronos.core.config import Config, Settings
from chronos.core.context import ApplicationContext

FEED = "https://github.com/python/cpython/releases.atom"
req = Request(FEED, headers={"User-Agent": "ChronosProbe/0.6"})
text = urlopen(req, timeout=20).read().decode("utf-8", "replace")
print("fetched", len(text), "bytes from", FEED)

cfg = Config(Path(tempfile.mkdtemp())/"home")
cfg.save_settings(Settings(network_enabled=True, allow_feeds=True))
ctx = ApplicationContext(cfg)
r = ctx.feeds.subscribe_from_text(FEED, text)
print(f"parser={r.parser}  feed='{r.title}'  entries={r.found}  new={r.new}")
for b in ctx.storage.by_period(ctx.storage.year_counts()[0][0], limit=5):
    print(f"  - {b.dt:%Y-%m-%d}  {b.title[:48]}")
# prove a feed item cites cleanly
any_item = ctx.storage.find_by_url_pattern("%github.com%")[0]
csl = ctx.provider().resolve_citation(any_item.url)
print("CSL:", {k: csl[k] for k in ("type","title","container-title","issued") if k in csl})
ctx.close()
