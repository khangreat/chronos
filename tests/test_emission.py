"""Resource emission tests: Chronos emits captured posts/threads as bridgespec
ResourceRefs (kind + typed CSL + relationships), the broker routes get_resource,
and the emitted CSL validates. Also asserts bridgespec 1.1 stays back-compatible.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridgespec  # noqa: E402
from bridgespec import ProviderRegistry, ResourceProvider, validate_csl_item  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.interop import ChronosProvider  # noqa: E402


class ContractVersionTest(unittest.TestCase):
    def test_bridgespec_11_backcompat(self):
        self.assertEqual(bridgespec.CONTRACT_VERSION, "1.1")
        self.assertTrue(bridgespec.compatible("1.0"))  # 1.0 consumers still work
        self.assertTrue(bridgespec.compatible("1.1"))
        self.assertTrue(hasattr(bridgespec, "ResourceRef"))


class EmissionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_emit_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")
        self.p = ChronosProvider(self.ctx)
        # a captured X thread: tweet 2 replies to tweet 1
        d = self.tmp
        (d / "t.js").write_text(
            'window.YTD.tweets.part0 = ['
            '{"tweet":{"id_str":"1","full_text":"root of the thread",'
            '"created_at":"Wed Oct 10 20:19:24 +0000 2018"}},'
            '{"tweet":{"id_str":"2","full_text":"the reply",'
            '"created_at":"Wed Oct 10 20:25:00 +0000 2018",'
            '"in_reply_to_status_id_str":"1"}}];')
        self.ctx.platform_import.import_x_tweets(d / "t.js")

    def tearDown(self):
        self.ctx.close()

    def test_provider_is_resource_provider(self):
        self.assertIsInstance(self.p, ResourceProvider)

    def test_get_resource_emits_kind_csl_and_relationships(self):
        ref = self.p.get_resource("https://twitter.com/i/web/status/2")
        self.assertEqual(ref["kind"], "social_post")
        self.assertEqual(ref["csl"]["type"], "post")            # typed by kind
        # the reply carries its thread relationship: reply_to -> tweet 1
        rels = {(r["rel"], r["url"]) for r in ref["relationships"]}
        self.assertIn(("reply_to", "https://twitter.com/i/web/status/1"), rels)

    def test_parent_side_relationship(self):
        ref = self.p.get_resource("https://twitter.com/i/web/status/1")
        rels = {(r["rel"], r["url"]) for r in ref["relationships"]}
        # tweet 1 is replied-to by tweet 2
        self.assertIn(("reply_to_by", "https://twitter.com/i/web/status/2"), rels)

    def test_emitted_csl_validates(self):
        ref = self.p.get_resource("https://twitter.com/i/web/status/1")
        errors = validate_csl_item(ref["csl"])
        self.assertEqual(errors, [], errors)

    def test_resources_by_kind(self):
        refs = self.p.resources_by_kind("social_post")
        self.assertEqual(len(refs), 2)

    def test_broker_routes_get_resource(self):
        reg = ProviderRegistry()
        reg.register(self.p)
        hit = reg.get_resource("https://twitter.com/i/web/status/1")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["url"], "https://twitter.com/i/web/status/1")
        self.assertIsNone(reg.get_resource("https://unknown.example/x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
