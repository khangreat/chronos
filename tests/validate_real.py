"""Validation on REAL captured pages from Mozilla's readability test corpus
(diverse: RTL, CJK, European langs, big news sites with ads). Runs the full
bookmark -> extract -> archive flow. Network probe, not a gated test.
"""
import sys, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chronos.core.context import ApplicationContext
from chronos.core.models import Bookmark
from chronos.web.extract import extract_content

RAW = "https://raw.githubusercontent.com/mozilla/readability/main/test/test-pages/{}/source.html"
# curated diverse real pages: RTL, Chinese, Japanese, French, German, big US news
CASES = ["rtl-1","rtl-2","qq","hukumusume","lemonde-1","heise","nytimes-1",
         "bbc-1","wikipedia","guardian-1","salon-1","folha"]
BOILER = ["subscribe","sign in","cookie","advertisement","newsletter"]

def fetch(url):
    return urlopen(Request(url, headers={"User-Agent":"ChronosValidate/0.12"}),
                   timeout=25).read().decode("utf-8","replace")

ctx = ApplicationContext.for_dir(Path(tempfile.mkdtemp())/"home")
print(f"{'case':<14}{'html KB':>8}{'text KB':>8}{'title':>7}{'extractor':>11}{'boiler':>7}")
print("-"*56)
ok=0
for name in CASES:
    try:
        html = fetch(RAW.format(name))
    except HTTPError as e:
        print(f"{name:<14} (skip {e.code})"); continue
    except Exception as e:
        print(f"{name:<14} (skip {e})"); continue
    p = extract_content(html, f"https://ex/{name}")
    leak = sum(1 for b in BOILER if b in p.text.lower())
    bid,_ = ctx.storage.upsert_bookmark(Bookmark(url=f"https://ex/{name}",
             title=name, date_added=1700000000, browser="Test"))
    ctx.archive.archive_from_html(bid, html)
    ok += 1
    print(f"{name:<14}{len(html)/1024:>8.0f}{len(p.text)/1024:>8.1f}"
          f"{('yes' if p.title else 'no'):>7}{p.extractor:>11}{leak:>7}")
print("-"*56)
print(f"processed {ok} real pages; archived offline: {ctx.storage.archive_count()}")
# spot-check: multi-script content survived into FTS
for term in ["news","中国","ニュース","الأخبار"]:
    n = len(ctx.search.search(term))
    if n: print(f"  FTS '{term}': {n} hit(s)")
ctx.close()
