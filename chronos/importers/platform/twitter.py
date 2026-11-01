"""X (Twitter) account-export parser.

The account archive ships JS files (tweets.js, like.js, …) shaped as
`window.YTD.<name>.part0 = [ {...}, ... ];`. This strips that assignment wrapper,
parses the JSON array, and normalises tweets and likes into records — including
`in_reply_to_status_id_str`, which lets Chronos rebuild threads. Pure parsing;
the service layer handles storage, packaging, provenance, and linking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

_STATUS = "https://twitter.com/i/web/status/"


@dataclass
class TweetRecord:
    url: str
    tweet_id: str
    text: str
    created_ts: Optional[int]
    in_reply_to: Optional[str]   # tweet id this replies to, or None


@dataclass
class LikeRecord:
    url: str
    tweet_id: str
    text: str


def _strip_wrapper(text: str) -> str:
    """Turn `window.YTD.tweets.part0 = [ ... ];` into the bare JSON array."""
    eq = text.find("=")
    if eq != -1 and text[:eq].strip().startswith("window.YTD"):
        text = text[eq + 1:]
    text = text.strip()
    if text.endswith(";"):
        text = text[:-1]
    return text.strip()


def parse_x_js(text: str) -> list:
    try:
        data = json.loads(_strip_wrapper(text))
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def _ts(created_at: Optional[str]) -> Optional[int]:
    if not created_at:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y",):
        try:
            return int(datetime.strptime(created_at, fmt).timestamp())
        except ValueError:
            continue
    return None


def _title(text: str, tid: str) -> str:
    t = " ".join((text or "").split())
    return (t[:70] + "…") if len(t) > 70 else (t or f"Tweet {tid}")


def parse_tweets(text: str) -> List[TweetRecord]:
    out: List[TweetRecord] = []
    for item in parse_x_js(text):
        tw = item.get("tweet", item) if isinstance(item, dict) else {}
        tid = tw.get("id_str") or tw.get("id")
        if not tid:
            continue
        body = tw.get("full_text") or tw.get("text") or ""
        out.append(TweetRecord(
            url=_STATUS + str(tid), tweet_id=str(tid), text=body,
            created_ts=_ts(tw.get("created_at")),
            in_reply_to=tw.get("in_reply_to_status_id_str")))
    return out


def parse_likes(text: str) -> List[LikeRecord]:
    out: List[LikeRecord] = []
    for item in parse_x_js(text):
        lk = item.get("like", item) if isinstance(item, dict) else {}
        tid = lk.get("tweetId") or lk.get("id")
        if not tid:
            continue
        out.append(LikeRecord(
            url=lk.get("expandedUrl") or (_STATUS + str(tid)),
            tweet_id=str(tid), text=lk.get("fullText") or ""))
    return out
