"""Related & semantic search — layered and pluggable.

Default backend is TF-IDF cosine (zero dependencies, fully offline), reusing the
multilingual tokenizer (whitespace tokens + CJK bigrams, stopword-filtered). It
powers `related(resource)` and a meaning-ranked `semantic_search(query)`, and is
fused with the existing FTS5/BM25 keyword search for `hybrid_search` (reciprocal
rank fusion — the documented best practice).

An optional dense-embedding backend can be plugged in without changing callers:
implement `EmbeddingBackend` (e.g. over Model2Vec — numpy-only, multilingual — or
sqlite-vec). It's detected at runtime and never required or auto-installed, the
same pattern as the optional trafilatura extractor.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..core.models import Bookmark
from .tagging_service import _STOP, _WORD


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF)


def tokenize(text: str) -> List[str]:
    """Terms for indexing: lowercased letter-words (>=2 chars, non-stopword) plus
    adjacent CJK character bigrams, keeping repeats so term frequency is real."""
    text = text or ""
    toks = [w.lower() for w in _WORD.findall(text)
            if len(w) >= 2 and w.lower() not in _STOP]
    cjk = [c for c in text if _is_cjk(c)]
    toks += [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return toks


def _doc_text(bm: Bookmark) -> str:
    parts = [bm.title or "", bm.page_text or bm.excerpt or "",
             " ".join(bm.tags or [])]
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Optional dense-embedding backend (plug-in seam)
# --------------------------------------------------------------------------- #
class EmbeddingBackend:
    name = "none"

    def available(self) -> bool:
        return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class Model2VecBackend(EmbeddingBackend):
    """Static multilingual embeddings via Model2Vec, if the user installs it
    (`pip install model2vec`). numpy-only, ~30 MB model, torch-free."""
    name = "model2vec"

    def __init__(self, model: str = "minishlab/potion-multilingual-128M"):
        self._model_name = model
        self._model = None

    def available(self) -> bool:
        try:
            import model2vec  # noqa: F401
            return True
        except Exception:
            return False

    def _load(self):
        if self._model is None:
            from model2vec import StaticModel
            self._model = StaticModel.from_pretrained(self._model_name)
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in self._load().encode(texts)]


# --------------------------------------------------------------------------- #
# TF-IDF index (default backend)
# --------------------------------------------------------------------------- #
class TfidfIndex:
    def __init__(self):
        self.ids: List[int] = []
        self.vectors: Dict[int, Dict[str, float]] = {}   # id -> term -> weight (L2-normed)
        self.idf: Dict[str, float] = {}

    def build(self, bookmarks: List[Bookmark]) -> None:
        tfs: Dict[int, Counter] = {}
        df: Counter = Counter()
        for bm in bookmarks:
            toks = tokenize(_doc_text(bm))
            if not toks:
                continue
            c = Counter(toks)
            tfs[bm.id] = c
            for term in c:
                df[term] += 1
        n = max(len(tfs), 1)
        self.idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}
        self.ids = list(tfs.keys())
        self.vectors = {}
        for bid, c in tfs.items():
            vec = {t: (1 + math.log(f)) * self.idf.get(t, 0.0)
                   for t, f in c.items()}
            norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
            self.vectors[bid] = {t: w / norm for t, w in vec.items()}

    def _query_vec(self, text: str) -> Dict[str, float]:
        c = Counter(tokenize(text))
        vec = {t: (1 + math.log(f)) * self.idf.get(t, 0.0) for t, f in c.items()}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        return {t: w / norm for t, w in vec.items()}

    @staticmethod
    def _cos(a: Dict[str, float], b: Dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(t, 0.0) for t, w in a.items())

    def related(self, bid: int, k: int) -> List[Tuple[int, float]]:
        base = self.vectors.get(bid)
        if not base:
            return []
        scored = [(oid, self._cos(base, v)) for oid, v in self.vectors.items()
                  if oid != bid]
        scored = [s for s in scored if s[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def search(self, query: str, k: int) -> List[Tuple[int, float]]:
        q = self._query_vec(query)
        if not q:
            return []
        scored = [(bid, self._cos(q, v)) for bid, v in self.vectors.items()]
        scored = [s for s in scored if s[1] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
class RelatedService:
    def __init__(self, ctx, backend: Optional[EmbeddingBackend] = None):
        self.ctx = ctx
        self.backend = backend
        self._index: Optional[TfidfIndex] = None
        self._emb: Dict[int, List[float]] = {}

    def reindex(self) -> int:
        bms = self.ctx.storage.all_bookmarks()
        self._index = TfidfIndex()
        self._index.build(bms)
        if self.backend and self.backend.available():
            texts = [_doc_text(b) for b in bms]
            vecs = self.backend.embed(texts)
            self._emb = {b.id: v for b, v in zip(bms, vecs)}
        return len(self._index.ids)

    def _idx(self) -> TfidfIndex:
        if self._index is None:
            self.reindex()
        return self._index

    @staticmethod
    def _dense_cos(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)

    def _hydrate(self, scored: List[Tuple[int, float]]):
        out = []
        for bid, score in scored:
            bm = self.ctx.storage.get(bid)
            if bm is not None:
                out.append((bm, round(score, 4)))
        return out

    def related(self, bookmark_id: int, k: int = 10):
        # dense backend if present, else TF-IDF
        if self._emb and bookmark_id in self._emb:
            base = self._emb[bookmark_id]
            scored = [(oid, self._dense_cos(base, v))
                      for oid, v in self._emb.items() if oid != bookmark_id]
            scored.sort(key=lambda x: x[1], reverse=True)
            return self._hydrate([s for s in scored if s[1] > 0][:k])
        return self._hydrate(self._idx().related(bookmark_id, k))

    def semantic_search(self, query: str, k: int = 20):
        if self._emb and self.backend:
            qv = self.backend.embed([query])[0]
            scored = [(bid, self._dense_cos(qv, v)) for bid, v in self._emb.items()]
            scored.sort(key=lambda x: x[1], reverse=True)
            return self._hydrate([s for s in scored if s[1] > 0][:k])
        return self._hydrate(self._idx().search(query, k))

    def hybrid_search(self, query: str, k: int = 20):
        """Reciprocal-rank fusion of FTS5/BM25 and semantic ranking."""
        lex = [b.id for b in self.ctx.search.search(query)]
        sem = [bid for bid, _ in self._idx().search(query, k * 2)]
        if self._emb and self.backend:
            sem = [bid for bid, _ in (
                lambda qv: sorted(
                    ((bid, self._dense_cos(qv, v)) for bid, v in self._emb.items()),
                    key=lambda x: x[1], reverse=True))(self.backend.embed([query])[0])][:k * 2]
        rrf: Dict[int, float] = {}
        for rank, bid in enumerate(lex):
            rrf[bid] = rrf.get(bid, 0.0) + 1.0 / (60 + rank)
        for rank, bid in enumerate(sem):
            rrf[bid] = rrf.get(bid, 0.0) + 1.0 / (60 + rank)
        ordered = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:k]
        return self._hydrate(ordered)

    def backend_name(self) -> str:
        return (self.backend.name if self.backend and self.backend.available()
                else "tfidf")
