"""Optional local embedding boundary. The production dependency is loaded on demand."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol

INSTALL_HINT = "pip install 'mnemobun-core[vector]'"
OFFLINE_ENV_VAR = "AGENT_MEMORY_OFFLINE"


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    def __init__(self, model: str):
        try:
            from fastembed import TextEmbedding
        except ImportError as error:
            raise RuntimeError(
                "Vector capability is enabled but optional embedding dependency is unavailable; "
                f"install it with: {INSTALL_HINT}"
            ) from error
        self._backend = TextEmbedding(
            model_name=model,
            local_files_only=os.environ.get(OFFLINE_ENV_VAR, "") == "1",
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [item.tolist() for item in self._backend.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class HttpEmbedder:
    """OpenAI-compatible /v1/embeddings client (stdlib only) — e.g. a local
    llama-server hosting bge-m3. No third-party dependency, so it works inside
    the read-only Hermes environment."""

    def __init__(self, model: str, url: str, *, timeout_seconds: float, batch_size: int):
        if not url:
            raise RuntimeError(
                "Vector capability is enabled with the http embedder but no endpoint URL is set; "
                "set index.embedder_url (e.g. http://127.0.0.1:8081)"
            )
        self._model = model
        self._url = url.rstrip("/")
        self._timeout = timeout_seconds
        self._batch_size = batch_size

    def _post(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.error
        import urllib.request

        payload = json.dumps({"input": texts, "model": self._model}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._url}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(
                f"embedding endpoint unreachable at {self._url} ({error}); "
                "check that the embedder service is running"
            ) from error
        items = sorted(body["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            out.extend(self._post(texts[start : start + self._batch_size]))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_embedder(config) -> Embedder:
    index = config.index
    if index.embedder_backend == "http":
        return HttpEmbedder(
            index.vector_model,
            index.embedder_url,
            timeout_seconds=index.embedder_timeout_seconds,
            batch_size=index.embedder_batch_size,
        )
    return FastEmbedder(index.vector_model)
