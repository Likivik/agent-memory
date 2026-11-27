"""Feature 5 acceptance: the dense (vector) leg changes recall results.

Uses a deterministic stub embedder — no model download in tests. The production
embedder (FastEmbedder, local ONNX) is exercised by the real backfill, not here.
"""

from __future__ import annotations

import hashlib

import pytest
from mnemobun.core.embeddings import FastEmbedder
from mnemobun.core.recall import Recall
from mnemobun.core.store import Store


class StubEmbedder:
    """Deterministic 64-dim vectors: hashed token buckets. Paraphrases share tokens,
    so this is a fair stand-in for 'semantically close' without a model."""

    def __init__(self, dim: int = 64):
        self._dim = dim

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in text.lower().split():
            bucket = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % self._dim
            vec[bucket] += 1.0
        norm = max(sum(v * v for v in vec) ** 0.5, 1e-9)
        return [v / norm for v in vec]

    def embed_documents(self, texts) -> list[list[float]]:
        return [self._vec(str(text)) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _vector_store(tmp_path, config, clock):
    config.index.vector_enabled = True
    store = Store(
        tmp_path / "vstore", config=config, clock=clock, writer="t",
        embedder=StubEmbedder(),
    )
    store.init()
    return store


def test_vector_recall_finds_paraphrase_bm25_misses(tmp_path, config, clock):
    store = _vector_store(tmp_path, config, clock)
    store.record(
        abstract="Deploys ship every Tuesday afternoon",
        type="preference", body="x", name="deploy-tuesday",
    )
    # BM25 query with zero token overlap — only the vector leg can match it.
    hits = Recall(store).recall("weekly release cadence schedule", limit=5)
    assert hits, "vector recall must return candidates"
    # The stub shares no tokens either; assert the vector leg ran by checking the
    # hit is the deploy record via nearest-neighbour on the stub space.
    best = hits[0]
    assert best.name == "deploy-tuesday"


def test_vector_disabled_keeps_bm25_only(tmp_path, config, clock):
    config.index.vector_enabled = False
    store = Store(tmp_path / "plain", config=config, clock=clock, writer="t")
    store.init()
    store.record(
        abstract="Deploys ship every Tuesday afternoon",
        type="preference", body="x", name="deploy-tuesday",
    )
    hits = Recall(store).recall("weekly release cadence schedule", limit=5)
    assert all(hit.name != "deploy-tuesday" for hit in hits)


def test_fastembedder_missing_dependency_error_names_the_extra(monkeypatch):
    # The dev venv HAS fastembed (installed with --extra vector); simulate the
    # production-missing case by breaking the import.
    import sys

    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(RuntimeError) as excinfo:
        FastEmbedder("BAAI/bge-small-en-v1.5")
    message = str(excinfo.value)
    assert "mnemobun-core[vector]" in message


def test_vector_enabled_without_dependency_fails_loud(tmp_path, config, clock, monkeypatch):
    """vector_enabled=True + a broken embedder factory is a config error: Store must
    fail LOUDLY, not silently drop the dense leg."""
    import mnemobun.core.store as store_module

    def broken(model):
        raise RuntimeError("Vector capability is enabled but optional embedding dependency"
                           " is unavailable; install it with: mnemobun-core[vector]")

    monkeypatch.setattr(store_module, "create_embedder", broken)
    config.index.vector_enabled = True
    with pytest.raises(RuntimeError) as excinfo:
        Store(tmp_path / "loud", config=config, clock=clock, writer="t")
    assert "mnemobun-core[vector]" in str(excinfo.value)
