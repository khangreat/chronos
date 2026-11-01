"""Save pages to the Internet Archive (Save Page Now 2), and archive.today links.

Saving publishes the page's address to archive.org, so it is gated by its own
capability ("archive_submit") on top of the network master switch. Without keys
the Archive allows about 3 saves a minute and 200 a day; with S3-style keys
("access:secret", from archive.org/account/s3.php) 7 a minute.

Flow: POST /save (url) -> job_id; poll /save/status/<job_id> until "success"
(-> timestamp, original_url) or "error". The snapshot lives at
https://web.archive.org/web/<timestamp>/<original_url>.

archive.today has no API (it asks people to solve a challenge), so Chronos only
builds the links that open it in your browser.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

BASE = "https://web.archive.org"
_UA = "ChronosArchive (+local; saving pages the user chose to archive)"


class ArchiveError(RuntimeError):
    pass


def _keys(settings) -> str:
    return (os.environ.get("CHRONOS_IA_KEYS") or getattr(settings, "ia_keys", "")
            or "").strip()


def wait_between(settings) -> float:
    """Seconds to leave between saves to stay within the Archive's limits."""
    return 9.0 if _keys(settings) else 21.0


def _call(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise ArchiveError("The Internet Archive says too many saves right now. "
                               "Try again in a few minutes.")
        if e.code in (401, 403):
            raise ArchiveError("The Internet Archive refused the keys. Check them in "
                               "Settings, or leave them empty.")
        raise ArchiveError(f"The Internet Archive answered with an error ({e.code}).")
    except urllib.error.URLError:
        raise ArchiveError("Couldn’t reach the Internet Archive.")
    except ValueError:
        raise ArchiveError("The Internet Archive sent back an unexpected answer.")


def save_page_now(url: str, settings, policy, base: str = BASE,
                  timeout: float = 180.0, poll: float = 5.0,
                  sleep: Callable[[float], None] = time.sleep) -> str:
    """Ask the Archive to capture `url`; return the snapshot address."""
    policy.require("archive_submit")
    headers = {"Accept": "application/json", "User-Agent": _UA}
    keys = _keys(settings)
    if keys:
        headers["Authorization"] = f"LOW {keys}"
    body = urllib.parse.urlencode({"url": url}).encode()
    job = _call(urllib.request.Request(f"{base}/save", data=body, headers=headers,
                                       method="POST"), 60)
    job_id = job.get("job_id")
    if not job_id:
        raise ArchiveError(job.get("message") or "The Internet Archive didn’t accept "
                           "this page.")
    waited = 0.0
    while True:
        st = _call(urllib.request.Request(f"{base}/save/status/{job_id}",
                                          headers=headers), 30)
        status = st.get("status")
        if status == "success":
            return (f"https://web.archive.org/web/{st['timestamp']}/"
                    f"{st.get('original_url') or url}")
        if status == "error":
            raise ArchiveError(st.get("message") or "The Internet Archive couldn’t "
                               "save this page.")
        if waited >= timeout:
            raise ArchiveError("Still saving after a few minutes. The Archive will "
                               "finish on its own; check back later.")
        sleep(poll)
        waited += poll


def archive_today_view(url: str) -> str:
    """Newest archive.today snapshot of a page (opens in the browser)."""
    return "https://archive.ph/newest/" + url


def archive_today_save(url: str) -> str:
    """archive.today's own save form, pre-filled (you confirm in the browser)."""
    return "https://archive.ph/?run=1&url=" + urllib.parse.quote(url, safe="")
