"""Shared-contract tests: Chronos satisfies the bridgespec protocols, its output
validates against the contract, and a bridgespec broker (simulating Command
Center) routes citations/links/quotes across registered providers.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridgespec  # the shared contract package
from bridgespec import (
    CitationProvider, LinkProvider, ProviderRegistry, QuoteProvider,
    validate_csl_item, validate_quotation,
)
from chronos.core.context import ApplicationContext
from chronos.core.models import Bookmark


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_contract_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://sqlite.org/fts5.html", title="FTS5",
            date_added=1_704_067_200, browser="Firefox",
            site_name="SQLite Docs", byline="Jane Roe",
            published_ts=1_714_550_400))
        self.ctx.storage.upsert_bookmark(Bookmark(
            url="https://www.youtube.com/watch?v=x", title="vid",
            date_added=1_700_000_000, browser="Firefox"))
        self.ctx.snippets.capture(self.bid, "bm25 ranks results.", locator="p1")
        self.provider = self.ctx.provider()

    def tearDown(self):
        self.ctx.close()

    def test_provider_satisfies_all_protocols(self):
        self.assertIsInstance(self.provider, CitationProvider)
        self.assertIsInstance(self.provider, LinkProvider)
        self.assertIsInstance(self.provider, QuoteProvider)

    def test_emitted_citation_validates(self):
        csl = self.provider.resolve_citation("https://sqlite.org/fts5.html")
        self.assertEqual(validate_csl_item(csl), [])  # no problems

    def test_emitted_quote_validates(self):
        q = self.provider.list_quotes()[0]
        self.assertEqual(validate_quotation(q), [])

    def test_contract_version_and_compat(self):
        self.assertEqual(bridgespec.CONTRACT_VERSION, "1.1")
        self.assertTrue(bridgespec.compatible("1.0"))  # 1.0 consumers still work
        self.assertTrue(bridgespec.compatible("1.1"))
        self.assertFalse(bridgespec.compatible("2.0"))  # different major
        self.assertTrue(bridgespec.compatible("1.0", "1.3"))  # newer minor ok

    def test_broker_routes_across_providers(self):
        # Command Center's role: a registry of providers.
        registry = ProviderRegistry()

        class OtherApp:  # a second app that only knows one URL
            def resolve_citation(self, url):
                if url == "https://other.app/x":
                    return {"type": "webpage", "title": "Other", "URL": url}
                return None

        registry.register(self.provider)     # Chronos
        registry.register(OtherApp())        # a peer app

        # Chronos answers for its URL...
        a = registry.resolve_citation("https://sqlite.org/fts5.html")
        self.assertEqual(a["container-title"], "SQLite Docs")
        # ...the peer answers for its own...
        b = registry.resolve_citation("https://other.app/x")
        self.assertEqual(b["title"], "Other")
        # ...and neither claims an unknown URL.
        self.assertIsNone(registry.resolve_citation("https://nobody.knows/y"))

    def test_broker_dedupes_links(self):
        registry = ProviderRegistry()
        registry.register(self.provider)
        yt = registry.find_links("youtube.com")
        self.assertTrue(any("youtube.com/watch" in r.url for r in yt))
        self.assertEqual(r"chronos", yt[0].source_app)

    def test_validator_catches_bad_item(self):
        problems = validate_csl_item({"title": "no type"})
        self.assertIn("missing 'type'", problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
