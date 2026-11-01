"""Related & semantic search tests: TF-IDF relatedness, semantic + hybrid
search, multilingual tokenization, and the pluggable embedding-backend seam.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.services.similarity import (  # noqa: E402
    EmbeddingBackend, Model2VecBackend, RelatedService, tokenize)


class TokenizeTest(unittest.TestCase):
    def test_latin_and_stopwords(self):
        t = tokenize("The quick brown fox and the lazy dog")
        self.assertIn("quick", t)
        self.assertNotIn("the", t)

    def test_cjk_bigrams(self):
        t = tokenize("人工知能")
        self.assertIn("人工", t)
        self.assertIn("工知", t)


class RelatedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_rel_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "home")

    def tearDown(self):
        self.ctx.close()

    def _bm(self, url, title, text=""):
        bid, _ = self.ctx.storage.upsert_bookmark(Bookmark(
            url=url, title=title, date_added=1, browser="F"))
        if text:
            self.ctx.storage.conn.execute(
                "UPDATE bookmarks SET page_text=? WHERE id=?", (text, bid))
            self.ctx.storage.conn.commit()
        return bid

    def test_related_ranks_similar_first(self):
        a = self._bm("https://x/a", "Brahui phonology",
                     "retroflex consonants in the Brahui Dravidian language")
        b = self._bm("https://x/b", "Dravidian retroflex sounds",
                     "retroflex consonants across Dravidian languages like Brahui")
        self._bm("https://x/c", "Cooking pasta",
                 "boil water add salt and pasta then drain")
        rel = self.ctx.related.related(a, k=5)
        self.assertTrue(rel)
        self.assertEqual(rel[0][0].id, b)   # the Dravidian doc, not the pasta one

    def test_semantic_search(self):
        self._bm("https://x/a", "Brahui phonology",
                 "retroflex consonants in Brahui")
        self._bm("https://x/c", "Cooking pasta", "boil water and salt")
        hits = self.ctx.related.semantic_search("Dravidian consonants Brahui")
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].url, "https://x/a")

    def test_hybrid_search_fuses(self):
        self._bm("https://x/a", "Surveillance law",
                 "intelligence agencies and data surveillance oversight")
        self._bm("https://x/b", "Garden tips", "plant tomatoes in spring")
        hits = self.ctx.related.hybrid_search("surveillance")
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].url, "https://x/a")

    def test_multilingual_related(self):
        a = self._bm("https://x/j1", "人工知能", "人工知能 技術 進歩")
        b = self._bm("https://x/j2", "人工知能の研究", "人工知能 研究 技術")
        self._bm("https://x/e", "English doc", "completely unrelated english text")
        rel = self.ctx.related.related(a, k=3)
        self.assertEqual(rel[0][0].id, b)

    def test_default_backend_is_tfidf(self):
        self._bm("https://x/a", "t", "some text here")
        self.ctx.related.reindex()
        self.assertEqual(self.ctx.related.backend_name(), "tfidf")

    def test_model2vec_backend_optional_and_absent(self):
        # not installed in this env → available() False, never required
        self.assertFalse(Model2VecBackend().available())

    def test_pluggable_dense_backend(self):
        # inject a fake deterministic embedding backend; related uses vectors
        class Fake(EmbeddingBackend):
            name = "fake"
            def available(self):
                return True
            def embed(self, texts):
                # 2-dim: (len, count of letter 'a') — crude but deterministic
                return [[float(len(t)), float(t.lower().count("a"))] for t in texts]
        svc = RelatedService(self.ctx, backend=Fake())
        self._bm("https://x/a", "aaaa aaaa", "aaaa")
        self._bm("https://x/b", "aaaa aaaa", "aaa")
        self._bm("https://x/c", "zzzz", "zzzz zzzz zzzz")
        svc.reindex()
        self.assertEqual(svc.backend_name(), "fake")
        a = self.ctx.storage.get_by_url("https://x/a").id
        rel = svc.related(a, k=2)
        self.assertTrue(rel)  # dense path produced results


if __name__ == "__main__":
    unittest.main(verbosity=2)
