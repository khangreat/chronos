"""Fetch a handful of REAL, structurally-different pages and run the extractor
on them — to see how it copes with server-rendered HTML, metadata-only shells,
plain-text, and SPA pages. Uses only allowlisted domains. Network-dependent, so
this is a probe, not a gated unit test.
"""

import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chronos.web.extract import extract_content  # noqa: E402

URLS = [
    "https://pypi.org/project/requests/",                 # rich metadata
    "https://github.com/python/cpython",                  # JS-heavy + og tags
    "https://raw.githubusercontent.com/psf/requests/main/README.md",  # plain text
    "https://crates.io/crates/serde",                     # SPA shell
]


def fetch(url):
    req = Request(url, headers={"User-Agent": "ChronosProbe/0.5"})
    with urlopen(req, timeout=15) as r:
        cs = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(cs, errors="replace")


for url in URLS:
    print("=" * 70)
    print(url)
    try:
        html = fetch(url)
    except Exception as e:
        print(f"  fetch failed: {e}")
        continue
    p = extract_content(html, url)
    print(f"  html bytes : {len(html):,}")
    print(f"  extractor  : {p.extractor}")
    print(f"  title      : {(p.title or '')[:70]}")
    print(f"  site_name  : {p.site_name}")
    print(f"  byline     : {p.byline}")
    print(f"  published  : {p.published_ts}")
    print(f"  text chars : {len(p.text):,}")
    print(f"  excerpt    : {(p.excerpt or '')[:110]}")
    print(f"  text head  : {p.text[:160].replace(chr(10),' ')}")
