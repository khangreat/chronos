"""Extension tests: native-messaging framing, the host's ingest-and-reply loop
over a real byte stream, and native-host manifest / install-path generation.
"""

from __future__ import annotations

import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.extension import install as inst  # noqa: E402
from chronos.extension.messaging import (  # noqa: E402
    HOST_NAME, read_message, write_message)
from chronos.extension.native_host import handle, run  # noqa: E402


def _framed(obj) -> bytes:
    data = json.dumps(obj).encode("utf-8")
    return struct.pack("@I", len(data)) + data


class FramingTest(unittest.TestCase):
    def test_round_trip(self):
        buf = io.BytesIO()
        write_message(buf, {"hello": "world", "n": 3})
        buf.seek(0)
        self.assertEqual(read_message(buf), {"hello": "world", "n": 3})

    def test_eof_returns_none(self):
        self.assertIsNone(read_message(io.BytesIO(b"")))


class HostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_ext_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def test_handle_capture(self):
        resp = handle(self.ctx, {
            "type": "capture", "url": "https://x.com/u/status/9",
            "title": "t", "selection": "a captured line"})
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["kind"], "social_post")
        self.assertTrue(resp["quoted"])
        self.assertIsNotNone(
            self.ctx.storage.get_by_url("https://x.com/u/status/9"))

    def test_handle_ping_and_bad_type(self):
        self.assertTrue(handle(self.ctx, {"type": "ping"})["pong"])
        self.assertFalse(handle(self.ctx, {"type": "nope"})["ok"])

    def test_run_processes_stream_and_replies(self):
        # two framed capture messages then EOF
        stdin = io.BytesIO(
            _framed({"type": "capture", "url": "https://site.example/a"}) +
            _framed({"type": "capture", "url": "https://site.example/b"}))
        stdout = io.BytesIO()
        run(self.ctx, stdin=stdin, stdout=stdout)
        stdout.seek(0)
        r1 = read_message(stdout)
        r2 = read_message(stdout)
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertEqual(self.ctx.storage.count(), 2)

    def test_run_survives_bad_capture(self):
        stdin = io.BytesIO(_framed({"type": "capture"}))  # no url
        stdout = io.BytesIO()
        run(self.ctx, stdin=stdin, stdout=stdout)
        stdout.seek(0)
        self.assertFalse(read_message(stdout)["ok"])  # error, not a crash


class InstallTest(unittest.TestCase):
    def test_chrome_manifest_has_origin(self):
        m = inst.host_manifest("abc123", "/path/host.sh", "chrome")
        self.assertEqual(m["name"], HOST_NAME)
        self.assertEqual(m["allowed_origins"], ["chrome-extension://abc123/"])

    def test_firefox_manifest_has_extensions(self):
        m = inst.host_manifest("me@x", "/path/host.sh", "firefox")
        self.assertEqual(m["allowed_extensions"], ["me@x"])

    def test_manifest_location_per_browser(self):
        home = Path("/home/u")
        chrome = inst.manifest_location("chrome", home=home, platform="linux")
        firefox = inst.manifest_location("firefox", home=home, platform="linux")
        self.assertTrue(chrome.as_posix().endswith(
            "google-chrome/NativeMessagingHosts/com.chronos.capture.json"))
        self.assertIn(".mozilla/native-messaging-hosts", firefox.as_posix())

    def test_install_writes_manifest_and_launcher(self):
        home = Path(tempfile.mkdtemp())
        paths = inst.install("abc123", "chrome", home=home)
        self.assertTrue(Path(paths["manifest"]).exists())
        self.assertTrue(Path(paths["launcher"]).exists())
        m = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(m["path"], paths["launcher"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
