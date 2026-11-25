"""HttpEmbedder (OpenAI-compatible endpoint) + embedder config knobs."""

from __future__ import annotations

import json

import pytest
from mnemobun.core.config import Config
from mnemobun.core.embeddings import HttpEmbedder, create_embedder


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def test_http_embedder_batches_and_orders(monkeypatch):
    captured: list = []
    def fake_urlopen(request, timeout=None):
        batch = json.loads(request.data.decode("utf-8"))["input"]
        captured.append(batch)
        return _FakeResponse(
            json.dumps(
                {
                    "data": [
                        {"index": i, "embedding": [float(len(batch)), float(i)]}
                        for i in range(len(batch))
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = HttpEmbedder("bge-m3", "http://127.0.0.1:8081", batch_size=2, timeout_seconds=5)
    out = embedder.embed_documents(["a", "b", "c"])
    assert [len(batch) for batch in captured] == [2, 1]
    assert out == [[2.0, 0.0], [2.0, 1.0], [1.0, 0.0]]


def test_http_embedder_loud_fail_when_endpoint_down():
    embedder = HttpEmbedder("bge-m3", "http://127.0.0.1:59999", batch_size=2, timeout_seconds=1)
    with pytest.raises(RuntimeError, match="embedding endpoint unreachable"):
        embedder.embed_query("x")


def test_http_embedder_requires_url():
    with pytest.raises(RuntimeError, match="embedder_url"):
        HttpEmbedder("bge-m3", "", batch_size=2, timeout_seconds=5)


def test_config_backend_switches_factory(monkeypatch):
    config = Config.default()
    config.index.vector_enabled = True
    config.index.embedder_backend = "http"
    config.index.embedder_url = "http://127.0.0.1:8081"
    config.index.vector_model = "bge-m3"
    embedder = create_embedder(config)
    assert isinstance(embedder, HttpEmbedder)
    assert embedder._url == "http://127.0.0.1:8081"


def test_new_embedder_knobs_leave_disabled_fingerprint_alone():
    config = Config.default()
    before = config.recall_fingerprint()
    config.index.embedder_backend = "http"
    config.index.embedder_url = "http://127.0.0.1:8081"
    assert config.recall_fingerprint() == before
    assert Config.default().recall_fingerprint() == "5cbd58b5e008eef3"
