"""Install the native-messaging host manifest so a browser can find it.

Each browser looks for a small JSON manifest in an OS-specific directory; the
manifest names the host, points at an executable, and lists which extensions may
talk to it. This writes a launcher that runs `python -m
chronos.extension.native_host` plus that manifest, in the right place.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict

from .messaging import HOST_NAME

# Directory (relative to the user's home) where each browser reads host manifests.
_LOCATIONS = {
    ("chrome", "linux"): ".config/google-chrome/NativeMessagingHosts",
    ("chromium", "linux"): ".config/chromium/NativeMessagingHosts",
    ("firefox", "linux"): ".mozilla/native-messaging-hosts",
    ("chrome", "darwin"): "Library/Application Support/Google/Chrome/NativeMessagingHosts",
    ("chromium", "darwin"): "Library/Application Support/Chromium/NativeMessagingHosts",
    ("firefox", "darwin"): "Library/Application Support/Mozilla/NativeMessagingHosts",
    # Windows uses the registry to point at a manifest; we still write the file.
    ("chrome", "win32"): "AppData/Local/Chronos/NativeMessagingHosts",
    ("firefox", "win32"): "AppData/Local/Chronos/NativeMessagingHosts",
    ("edge", "win32"): "AppData/Local/Chronos/NativeMessagingHosts",
    ("edge", "linux"): ".config/microsoft-edge/NativeMessagingHosts",
    ("edge", "darwin"): "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
}


def _os_key(platform: str) -> str:
    if platform.startswith("linux"):
        return "linux"
    if platform == "darwin":
        return "darwin"
    if platform.startswith("win"):
        return "win32"
    return "linux"


def manifest_location(browser: str, home: Path = None,
                      platform: str = None) -> Path:
    home = home or Path.home()
    osk = _os_key(platform or sys.platform)
    rel = _LOCATIONS.get((browser, osk))
    if rel is None:
        raise ValueError(f"Unsupported browser/OS: {browser}/{osk}")
    return home / rel / f"{HOST_NAME}.json"


def host_manifest(extension_id: str, host_path: str, browser: str) -> Dict:
    m = {
        "name": HOST_NAME,
        "description": "Chronos capture native host",
        "path": host_path,
        "type": "stdio",
    }
    if browser == "firefox":
        m["allowed_extensions"] = [extension_id]
    else:  # chrome / chromium
        m["allowed_origins"] = [f"chrome-extension://{extension_id}/"]
    return m


def host_command() -> str:
    """How the browser starts Chronos's helper. From source: this Python with
    `-m chronos.extension.native_host`. From the packaged app: the console
    program `chronos-cli.exe extension host` beside Chronos.exe (the windowed
    Chronos.exe has no input/output for the browser to talk through)."""
    if getattr(sys, "frozen", False):
        name = "chronos-cli.exe" if sys.platform.startswith("win") else "chronos-cli"
        return f'"{Path(sys.executable).resolve().with_name(name)}" extension host'
    return f'"{sys.executable}" -m chronos.extension.native_host'


def _launcher_path(target_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        p = target_dir / "chronos_host.bat"
        p.write_text(f'@echo off\r\n{host_command()}\r\n')
    else:
        p = target_dir / "chronos_host.sh"
        p.write_text(f'#!/bin/sh\nexec {host_command()}\n')
        os.chmod(p, 0o755)
    return p


def install(extension_id: str, browser: str = "chrome", home: Path = None) -> Dict:
    """Write the launcher + manifest. Returns the paths written. On Windows the
    caller must also add a registry key pointing at the manifest (printed)."""
    loc = manifest_location(browser, home=home)
    loc.parent.mkdir(parents=True, exist_ok=True)
    launcher = _launcher_path(loc.parent)
    manifest = host_manifest(extension_id, str(launcher), browser)
    loc.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest": str(loc), "launcher": str(launcher),
            "browser": browser, "needs_registry": sys.platform.startswith("win")}


def unpack_to(dest) -> Path:
    """Copy the WebExtension files into `dest` (for 'Load unpacked')."""
    import shutil
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).parent / "webext"
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dest / f.name)
    return dest


_REG_KEYS = {
    "firefox": "Software\\Mozilla\\NativeMessagingHosts",
    "chrome": "Software\\Google\\Chrome\\NativeMessagingHosts",
    "chromium": "Software\\Chromium\\NativeMessagingHosts",
    "edge": "Software\\Microsoft\\Edge\\NativeMessagingHosts",
}


def registry_command(manifest_path: str, browser: str) -> str:
    """The one Windows command that tells the browser where the host lives."""
    key = _REG_KEYS.get(browser, _REG_KEYS["chrome"])
    return (f'reg add "HKCU\\{key}\\{HOST_NAME}" /ve /t REG_SZ '
            f'/d "{manifest_path}" /f')


def register_windows(manifest_path: str, browser: str) -> bool:
    """Write the per-user registry entry (HKEY_CURRENT_USER, no admin needed).
    Returns False off Windows or if the write fails."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        key = _REG_KEYS.get(browser, _REG_KEYS["chrome"]) + "\\" + HOST_NAME
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest_path))
        return True
    except OSError:
        return False
