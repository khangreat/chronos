"""End-to-end Core tests. Everything runs in an isolated temp CHRONOS_HOME,
never against the real profile. We build, import, and measure — not assert from
source inspection.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.migrations import current_target_version  # noqa: E402
from chronos.net.policy import NetworkDisabled  # noqa: E402
from tests.fixtures import (  # noqa: E402
    build_chromium_bookmarks,
    build_firefox_places,
    build_netscape_html,
)


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_test_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.fx = self.tmp / "places.sqlite"
        self.cr = self.tmp / "Bookmarks"
        self.html = self.tmp / "bm.html"
        build_firefox_places(self.fx)
        build_chromium_bookmarks(self.cr)
        build_netscape_html(self.html)

    def tearDown(self):
        self.ctx.close()

    # -- import correctness ------------------------------------------------- #
    def test_firefox_import_counts_and_filters_place_uris(self):
        r = self.ctx.bookmarks.import_from("firefox", self.fx)
        # 3 real bookmarks; the place: URI must be filtered out.
        self.assertEqual(r.found, 3)
        self.assertEqual(r.inserted, 3)

    def test_firefox_timestamp_epoch_is_correct(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        years = {b.year for b in self.ctx.bookmarks.by_year(2024)}
        self.assertEqual(years, {2024})
        # The 2024 Python Docs bookmark lands in Jan.
        pyt = [b for b in self.ctx.bookmarks.by_year(2024)
               if "python.org" in b.url][0]
        self.assertEqual((pyt.year, pyt.month), (2024, 1))

    def test_chromium_webkit_epoch_is_correct(self):
        r = self.ctx.bookmarks.import_from("chrome", self.cr)
        self.assertEqual(r.found, 2)  # Rust Book + Hacker News
        rust = self.ctx.search.search("rust")
        self.assertTrue(rust)
        self.assertEqual(rust[0].year, 2024)  # not 1601, not 5000

    def test_chromium_nested_folder_name(self):
        self.ctx.bookmarks.import_from("chrome", self.cr)
        hn = self.ctx.search.search("hacker")[0]
        self.assertEqual(hn.folder_name, "News")

    def test_html_import(self):
        r = self.ctx.bookmarks.import_html(self.html)
        self.assertEqual(r.found, 3)
        fts = self.ctx.search.search("fts5")
        self.assertEqual(fts[0].folder_name, "Learning")

    # -- dedupe ------------------------------------------------------------- #
    def test_reimport_does_not_duplicate(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        second = self.ctx.bookmarks.import_from("firefox", self.fx)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(self.ctx.bookmarks.count(), 3)

    # -- search ------------------------------------------------------------- #
    def test_fts_search_ranks_and_matches(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        res = self.ctx.search.search("python")
        self.assertTrue(any("python.org" in b.url for b in res))

    def test_search_survives_malformed_input(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        # A stray quote is invalid FTS syntax; must fall back, not raise.
        try:
            self.ctx.search.search('py"thon')
        except Exception as e:  # pragma: no cover
            self.fail(f"search raised on malformed input: {e}")

    # -- stats/timeline ----------------------------------------------------- #
    def test_stats_year_breakdown(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        by_year = dict(self.ctx.stats.stats().by_year)
        self.assertEqual(by_year, {2024: 1, 2023: 1, 2022: 1})

    # -- schema/migration --------------------------------------------------- #
    def test_schema_version_is_current(self):
        self.assertEqual(self.ctx.storage.version, current_target_version())
        self.assertGreaterEqual(current_target_version(), 1)

    # -- privacy gate ------------------------------------------------------- #
    def test_network_disabled_by_default(self):
        self.assertFalse(self.ctx.network.is_allowed("link_check"))
        with self.assertRaises(NetworkDisabled):
            self.ctx.network.require("link_check")

    def test_network_gate_opens_only_with_both_flags(self):
        from chronos.core.config import Settings
        from chronos.net.policy import NetworkPolicy
        # master off, capability on -> still blocked
        p = NetworkPolicy(Settings(network_enabled=False, allow_wayback=True))
        self.assertFalse(p.is_allowed("wayback"))
        # both on -> allowed
        p2 = NetworkPolicy(Settings(network_enabled=True, allow_wayback=True))
        self.assertTrue(p2.is_allowed("wayback"))

    # -- multi-source ------------------------------------------------------- #
    def test_all_three_sources_coexist(self):
        self.ctx.bookmarks.import_from("firefox", self.fx)
        self.ctx.bookmarks.import_from("chrome", self.cr)
        self.ctx.bookmarks.import_html(self.html)
        self.assertEqual(self.ctx.bookmarks.count(), 8)  # 3 + 2 + 3
        browsers = dict(self.ctx.stats.stats().by_browser)
        self.assertEqual(browsers, {"Firefox": 3, "Chrome": 2, "HTML": 3})


if __name__ == "__main__":
    unittest.main(verbosity=2)
