"""AutoTagger — derive apt tags from a bookmark's content and metadata.

Local, dependency-free, and multi-script aware:
  - a source tag from the site/domain,
  - a script tag for non-Latin content (arabic, cjk, hebrew, cyrillic),
  - topical keyword tags: whitespace tokens for space-separated scripts
    (stopword-filtered across several languages), or character bigrams for
    CJK text (which isn't space-separated).

Tags are suggestions; `auto_tag` applies them (merging with any existing tags).
No frequency corpus is needed — term frequency within the page is enough for
useful topical tags.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional
from urllib.parse import urlsplit

# Compact multi-language stopword set (high-frequency function words).
_STOP = set("""
the a an and or but of to in on at for with from by as is are was were be been
being this that these those it its it's you your we our they their he she his her
i me my mine not no yes do does did have has had will would can could should may
about into over under out up down off then than too very just also more most some
any all each other such only own same so if while when where which who whom what
le la les un une des du de et ou mais dans sur pour avec par comme est sont être
cette ces ont leur nous vous ils elle aux ce se ne qui pas plus fait faire tout
der die das und oder aber mit von zu den dem ein eine ist sind war werden auch
gibt schon noch beim wird kann einen einem eines nach über auf aus dass sich
el los las y o pero en con por para como es son fue ser una uno como más muy
está están este esta estos esa ese sus han hay entre sobre desde
o os as um uma e ou mas em com por para que como não sim mais muito está são
pelo pela dos das seu sua foi ter sobre entre quando
для что как это так его или уже быть был при она они мы вы все это когда
في من على إلى عن مع هذا هذه ذلك التي الذي كان قد لا ما هو هي نحن هم كل بعد
""".split())

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)  # letters only, no digits/underscore


def _dominant_script(text: str) -> str:
    c = Counter()
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            c["arabic"] += 1
        elif 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF:
            c["cjk"] += 1
        elif 0x0590 <= o <= 0x05FF:
            c["hebrew"] += 1
        elif 0x0400 <= o <= 0x04FF:
            c["cyrillic"] += 1
        elif ch.isalpha():
            c["latin"] += 1
    return c.most_common(1)[0][0] if c else "latin"


def _slug(text: str) -> str:
    text = re.sub(r"^www\.", "", text.strip().lower())
    text = re.sub(r"\.(com|org|net|io|gov|edu|news|info|co)(\.[a-z]{2})?$", "", text)
    text = re.sub(r"[^\w\u0080-\uFFFF]+", "-", text).strip("-")
    return text[:40]


def _cjk_bigrams(text: str, top: int) -> List[str]:
    chars = [c for c in text if 0x3040 <= ord(c) <= 0x30FF
             or 0x4E00 <= ord(c) <= 0x9FFF or 0xAC00 <= ord(c) <= 0xD7AF]
    grams = Counter("".join(pair) for pair in zip(chars, chars[1:]))
    return [g for g, n in grams.most_common(top * 3) if n >= 2][:top]


def _keywords(text: str, script: str, top: int) -> List[str]:
    if script == "cjk":
        return _cjk_bigrams(text, top)
    words = [w.lower() for w in _WORD.findall(text)]
    freq = Counter(w for w in words if len(w) >= 4 and w not in _STOP)
    return [w for w, n in freq.most_common(top * 2) if n >= 2][:top]


class AutoTagger:
    def __init__(self, ctx):
        self.ctx = ctx

    def suggest_tags(self, bookmark, max_tags: int = 6) -> List[str]:
        tags: List[str] = []
        # source
        host = urlsplit(bookmark.url).hostname or ""
        src = _slug(bookmark.site_name or host)
        if src:
            tags.append(src)
        # script (only when informative, i.e. non-Latin)
        text = f"{bookmark.title or ''} {bookmark.page_text or bookmark.excerpt or ''}"
        script = _dominant_script(text)
        if script != "latin":
            tags.append(script)
        # topical keywords
        for kw in _keywords(text, script, top=max_tags):
            if kw not in tags:
                tags.append(kw)
        return tags[:max_tags]

    def auto_tag(self, bookmark_id: int, apply: bool = True,
                 merge: bool = True, max_tags: int = 6) -> List[str]:
        bm = self.ctx.storage.get(bookmark_id)
        if bm is None:
            raise ValueError(f"No bookmark id={bookmark_id}")
        suggested = self.suggest_tags(bm, max_tags=max_tags)
        if apply:
            final = sorted(set(bm.tags) | set(suggested)) if merge else suggested
            self.ctx.storage.set_tags(bookmark_id, final)
            return final
        return suggested

    def auto_tag_all(self, limit: int = 0) -> int:
        n = 0
        for b in self.ctx.storage.all_bookmarks(limit):
            self.auto_tag(b.id)
            n += 1
        return n
