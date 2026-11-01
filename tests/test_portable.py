"""v0.35 "Windows portable": where the archive lives when Chronos runs from the
portable folder, the first-run choice about an earlier archive (nothing moved,
nothing split), the browser helper from the packaged app, and the self-test.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core import config  # noqa: E402

MARKER_TEXT = Path(__file__).resolve().parents[1].joinpath(
    "packaging", "windows", "portable.txt").read_text(encoding="utf-8")


class Frozen:
    """Pretend to be Chronos.exe in `prog`, with `home` as the user folder."""

    def __init__(self, prog: Path, home: Path):
        self.patches = [
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(prog / "Chronos.exe")),
            mock.patch.object(Path, "home", classmethod(lambda cls: home)),
            mock.patch.dict(os.environ, {}, clear=False),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        os.environ.pop("CHRONOS_HOME", None)
        return self

    def __exit__(self, *a):
        for p in reversed(self.patches):
            p.stop()


def _legacy(home: Path) -> Path:
    d = home / ".chronos_archive"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "bookmarks.db")
    con.execute("CREATE TABLE marker (x)"); con.execute("INSERT INTO marker VALUES (42)")
    con.commit(); con.close()
    (d / "archives").mkdir(); (d / "archives" / "page.html.gz").write_bytes(b"x")
    return d


class PortableDirTest(unittest.TestCase):
    def setUp(self):
        t = Path(tempfile.mkdtemp(prefix="chronos_port_"))
        self.prog, self.home = t / "Chronos", t / "home"
        self.prog.mkdir(); self.home.mkdir()

    def _marker(self):
        m = self.prog / "portable.txt"
        m.write_text(MARKER_TEXT, encoding="utf-8")
        return m

    def test_from_source_uses_the_user_folder(self):
        with mock.patch.object(Path, "home", classmethod(lambda cls: self.home)), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONOS_HOME", None)
            self.assertEqual(config.default_app_dir(), self.home / ".chronos_archive")

    def test_without_marker_the_exe_uses_the_user_folder(self):
        with Frozen(self.prog, self.home):
            self.assertEqual(config.default_app_dir(), self.home / ".chronos_archive")

    def test_marker_keeps_data_beside_the_program(self):
        self._marker()
        with Frozen(self.prog, self.home):
            self.assertEqual(config.default_app_dir(), self.prog / "data")
            self.assertTrue((self.prog / "data").is_dir())

    def test_data_line_chooses_a_folder(self):
        m = self._marker()
        config.record_portable_choice(m, str(self.home / "elsewhere"))
        with Frozen(self.prog, self.home):
            self.assertEqual(config.default_app_dir(), self.home / "elsewhere")
        self.assertIn("This file makes Chronos portable", m.read_text("utf-8"))  # kept
        config.record_portable_choice(m, "data")
        self.assertEqual(m.read_text("utf-8").count("\ndata="), 1)             # replaced

    def test_chronos_home_still_wins(self):
        self._marker()
        with Frozen(self.prog, self.home):
            os.environ["CHRONOS_HOME"] = str(self.home / "env")
            self.assertEqual(config.default_app_dir(), self.home / "env")

    def test_read_only_folder_falls_back(self):
        self._marker()
        with Frozen(self.prog, self.home), \
                mock.patch.object(Path, "mkdir", side_effect=PermissionError("ro")):
            self.assertEqual(config.default_app_dir(), self.home / ".chronos_archive")

    def test_earlier_archive_is_not_split_before_choosing(self):
        self._marker(); _legacy(self.home)
        with Frozen(self.prog, self.home):
            # e.g. chronos-cli.exe run before the window was ever opened
            self.assertEqual(config.default_app_dir(), self.home / ".chronos_archive")
            self.assertFalse((self.prog / "data" / "bookmarks.db").exists())


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        t = Path(tempfile.mkdtemp(prefix="chronos_first_"))
        self.prog, self.home = t / "Chronos", t / "home"
        self.prog.mkdir(); self.home.mkdir()
        (self.prog / "portable.txt").write_text(MARKER_TEXT, encoding="utf-8")
        self.legacy = _legacy(self.home)

    def _run(self, answer):
        from chronos.gui.app import portable_first_run
        asked = []
        with Frozen(self.prog, self.home):
            got = portable_first_run(ask=lambda p: asked.append(p) or answer)
            where = config.default_app_dir()
        return got, asked, where

    def test_copy_keeps_the_original(self):
        got, asked, where = self._run("copy")
        self.assertEqual((got, asked), ("copy", [self.legacy]))
        self.assertEqual(where, self.prog / "data")
        con = sqlite3.connect(where / "bookmarks.db")
        self.assertEqual(con.execute("SELECT x FROM marker").fetchone()[0], 42); con.close()
        self.assertTrue((where / "archives" / "page.html.gz").exists())
        self.assertTrue((self.legacy / "bookmarks.db").exists())        # nothing moved
        self.assertTrue((self.legacy / "archives" / "page.html.gz").exists())

    def test_keep_using_it_there(self):
        got, _, where = self._run("keep")
        self.assertEqual(where, self.legacy)
        self.assertFalse((self.prog / "data" / "bookmarks.db").exists())

    def test_start_new(self):
        _, _, where = self._run("new")
        self.assertEqual(where, self.prog / "data")
        self.assertTrue((self.legacy / "bookmarks.db").exists())

    def test_closing_asks_again_and_uses_the_earlier_archive(self):
        got, _, where = self._run(None)
        self.assertIsNone(got)
        self.assertEqual(where, self.legacy)
        _, asked, _ = self._run("copy")
        self.assertEqual(asked, [self.legacy])                           # asked again

    def test_asked_only_once(self):
        self._run("copy")
        _, asked, _ = self._run("keep")
        self.assertEqual(asked, [])

    def test_no_earlier_archive_no_question(self):
        import shutil
        shutil.rmtree(self.legacy)
        got, asked, where = self._run("copy")
        self.assertEqual((got, asked, where), (None, [], self.prog / "data"))


class HostCommandTest(unittest.TestCase):
    def test_from_source(self):
        from chronos.extension.install import host_command
        self.assertIn("-m chronos.extension.native_host", host_command())

    def test_from_the_packaged_app_uses_the_console_program(self):
        from chronos.extension.install import host_command
        prog = Path(tempfile.mkdtemp())
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(prog / "Chronos.exe")), \
                mock.patch.object(sys, "platform", "win32"):
            cmd = host_command()
        self.assertTrue(cmd.endswith('chronos-cli.exe" extension host'), cmd)
        self.assertNotIn("-m chronos", cmd)


class SelftestTest(unittest.TestCase):
    def test_core_selftest_passes_and_reports(self):
        from chronos.selftest import run_selftest
        out = Path(tempfile.mkdtemp()) / "r.txt"
        with mock.patch("sys.stdout", None):            # like the windowed .exe
            self.assertEqual(run_selftest(gui=False, report=str(out)), 0)
        text = out.read_text("utf-8")
        self.assertIn("PASS  translations", text)
        self.assertTrue(text.rstrip().endswith("all checks passed"))

    def test_selftest_fails_loudly(self):
        from chronos.selftest import run_selftest
        out = Path(tempfile.mkdtemp()) / "r.txt"
        with mock.patch("chronos.gui.i18n.available_locales", return_value=["en"]), \
                mock.patch("sys.stdout", None):
            self.assertEqual(run_selftest(report=str(out)), 1)
        self.assertIn("FAIL  translations", out.read_text("utf-8"))

    def test_gui_selftest(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 not installed")
        from chronos.selftest import run_selftest
        out = Path(tempfile.mkdtemp()) / "r.txt"
        with mock.patch("sys.stdout", None):
            self.assertEqual(run_selftest(gui=True, report=str(out)), 0,
                             out.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
