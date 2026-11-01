"""Find every browser profile on this computer — every browser, every profile.

Chromium-family browsers keep a "User Data" folder with one sub-folder per
profile (`Default`, `Profile 1`, …); each holds `Bookmarks` (JSON) and
`History` (SQLite). The names people gave their profiles ("Work", "Personal")
are in `Local State`. Firefox-family browsers keep a `Profiles` folder; each
profile holds `places.sqlite` (bookmarks and history together), named in
`profiles.ini`.

Before v0.36 Chronos looked in the wrong place on Windows and Linux (it missed
"User Data" and used macOS folder names), so Chrome, Edge, Brave and Vivaldi
were never found there, and only one profile per browser was ever read.
"""

from __future__ import annotations

import configparser
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class BrowserProfile:
    browser: str                    # "Chrome", "Edge", "Firefox", …
    family: str                     # "chromium" | "firefox"
    profile: str                    # the profile's own name ("Work") or folder
    folder: Path
    bookmarks: Optional[Path]       # chromium: Bookmarks; firefox: places.sqlite
    history: Optional[Path]         # chromium: History;   firefox: places.sqlite

    @property
    def label(self) -> str:
        return self.browser if self.profile in ("", "Default", "default") \
            else f"{self.browser} — {self.profile}"


def _win_dir(env: str, fallback: str) -> Path:
    v = os.environ.get(env)
    return Path(v) if v else Path.home() / fallback


def _chromium_roots(platform: str) -> List[tuple]:
    """(browser, user-data folder) candidates for this OS."""
    home = Path.home()
    if platform.startswith("win"):
        local = _win_dir("LOCALAPPDATA", "AppData/Local")
        roaming = _win_dir("APPDATA", "AppData/Roaming")
        return [("Chrome", local / "Google/Chrome/User Data"),
                ("Chrome Beta", local / "Google/Chrome Beta/User Data"),
                ("Edge", local / "Microsoft/Edge/User Data"),
                ("Brave", local / "BraveSoftware/Brave-Browser/User Data"),
                ("Vivaldi", local / "Vivaldi/User Data"),
                ("Chromium", local / "Chromium/User Data"),
                ("Opera", roaming / "Opera Software/Opera Stable"),
                ("Opera GX", roaming / "Opera Software/Opera GX Stable")]
    if platform == "darwin":
        sup = home / "Library/Application Support"
        return [("Chrome", sup / "Google/Chrome"), ("Edge", sup / "Microsoft Edge"),
                ("Brave", sup / "BraveSoftware/Brave-Browser"),
                ("Vivaldi", sup / "Vivaldi"), ("Chromium", sup / "Chromium"),
                ("Arc", sup / "Arc/User Data"),
                ("Opera", sup / "com.operasoftware.Opera")]
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [("Chrome", cfg / "google-chrome"), ("Chrome Beta", cfg / "google-chrome-beta"),
            ("Edge", cfg / "microsoft-edge"), ("Brave", cfg / "BraveSoftware/Brave-Browser"),
            ("Vivaldi", cfg / "vivaldi"), ("Chromium", cfg / "chromium"),
            ("Chromium", home / "snap/chromium/common/chromium"),
            ("Chrome", home / ".var/app/com.google.Chrome/config/google-chrome"),
            ("Brave", home / ".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser"),
            ("Opera", cfg / "opera")]


def _chromium_names(root: Path) -> Dict[str, str]:
    try:
        st = json.loads((root / "Local State").read_text(encoding="utf-8"))
        cache = st.get("profile", {}).get("info_cache", {})
        return {d: (v.get("name") or d) for d, v in cache.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def _chromium_profiles(browser: str, root: Path) -> List[BrowserProfile]:
    if not root.is_dir():
        return []
    names = _chromium_names(root)
    folders = [root] + sorted(
        (p for p in root.iterdir() if p.is_dir()
         and (p.name == "Default" or p.name.startswith("Profile "))),
        key=lambda p: (p.name != "Default", p.name))
    out = []
    for f in folders:
        bm, hi = f / "Bookmarks", f / "History"
        if not (bm.is_file() or hi.is_file()):
            continue
        out.append(BrowserProfile(
            browser, "chromium", names.get(f.name, "" if f == root else f.name), f,
            bm if bm.is_file() else None, hi if hi.is_file() else None))
    return out


def _firefox_roots(platform: str) -> List[tuple]:
    home = Path.home()
    if platform.startswith("win"):
        r = _win_dir("APPDATA", "AppData/Roaming")
        return [("Firefox", r / "Mozilla/Firefox"), ("LibreWolf", r / "librewolf"),
                ("Waterfox", r / "Waterfox"), ("Floorp", r / "Floorp"),
                ("Zen", r / "zen"), ("Tor Browser", home / "Desktop/Tor Browser/Browser/TorBrowser/Data/Browser")]
    if platform == "darwin":
        sup = home / "Library/Application Support"
        return [("Firefox", sup / "Firefox"), ("LibreWolf", sup / "librewolf"),
                ("Waterfox", sup / "Waterfox"), ("Floorp", sup / "Floorp"),
                ("Zen", sup / "zen"), ("Tor Browser", sup / "TorBrowser-Data/Browser")]
    return [("Firefox", home / ".mozilla/firefox"),
            ("Firefox", home / "snap/firefox/common/.mozilla/firefox"),
            ("Firefox", home / ".var/app/org.mozilla.firefox/.mozilla/firefox"),
            ("LibreWolf", home / ".librewolf"), ("Waterfox", home / ".waterfox"),
            ("Floorp", home / ".floorp"), ("Zen", home / ".zen"),
            ("Mullvad Browser", home / ".mullvad/mullvadbrowser/Browser/profile.default"),
            ("Tor Browser", home / ".tor-browser/app/Browser/TorBrowser/Data/Browser")]


def _firefox_names(root: Path) -> Dict[str, str]:
    ini = root / "profiles.ini"
    out: Dict[str, str] = {}
    if not ini.is_file():
        return out
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(ini, encoding="utf-8")
    except (configparser.Error, OSError):
        return out
    for sec in cp.sections():
        if cp.has_option(sec, "Path") and cp.has_option(sec, "Name"):
            out[Path(cp.get(sec, "Path").replace("\\", "/")).name] = cp.get(sec, "Name")
    return out


def _firefox_profiles(browser: str, root: Path) -> List[BrowserProfile]:
    if not root.is_dir():
        return []
    names = _firefox_names(root)
    places = sorted(set(root.glob("*/places.sqlite")) | set(root.glob("Profiles/*/places.sqlite"))
                    | ({root / "places.sqlite"} if (root / "places.sqlite").is_file() else set()))
    out = []
    for p in places:
        name = names.get(p.parent.name) or p.parent.name.split(".", 1)[-1]
        out.append(BrowserProfile(browser, "firefox", name, p.parent, p, p))
    out.sort(key=lambda b: ("default" not in b.profile.lower(), b.profile))
    return out


def discover(platform: Optional[str] = None) -> List[BrowserProfile]:
    """Every browser profile found on this computer, each once."""
    platform = platform or sys.platform
    found: List[BrowserProfile] = []
    seen = set()
    for browser, root in _chromium_roots(platform):
        for p in _chromium_profiles(browser, root):
            if p.folder.resolve() not in seen:
                seen.add(p.folder.resolve()); found.append(p)
    for browser, root in _firefox_roots(platform):
        for p in _firefox_profiles(browser, root):
            if p.folder.resolve() not in seen:
                seen.add(p.folder.resolve()); found.append(p)
    return found
