"""The library-side distiller: the store's config names who reasons, the host CLI by default.

One extraction for every host (ADR-002 as amended). What is sent and what the reply may do
are decided in the core; this module only picks the pipe the text travels through. A host
whose dialect has an MCP posture runs as a tool-use agent over the Write toolkit; the rest
keep the text protocol.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from mnemobun.core.config import (
    REASONER_ENDPOINT,
    REASONER_HOST,
    TOOL_MODE_TEXT,
    ExecutorConfig,
)
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.core.store import Store

from .credentials import VertexCredentials
from .reasoners import EndpointReasoner, EndpointTextReasoner

HOST_REASONER_REMOVED = (
    "host reasoners were removed from memory jobs (2026-11-24): one completion is "
    "one call, and only a direct endpoint can be counted and bounded. configure one: "
    "mnemobun brain config write --endpoint <url> --key-env <env> --model <m>"
)


class CountedAsk:
    """The choke point: every model call here is counted against the spend guard."""

    def __init__(self, ask: Callable[[str], str], store: Store) -> None:
        self._ask = ask
        self._store = store
        # one id per operation, so max_calls_per_run binds outside feed runs too
        self._run_id = f"ask-{uuid.uuid4().hex}"

    def __call__(self, prompt: str) -> str:
        from mnemobun.core import spend

        spend.record_call(
            self._store,
            run_id=spend.current_run_id() or self._run_id,
            prompt_chars=len(prompt),
        )
        return self._ask(prompt)

    def __getattr__(self, name: str) -> object:
        if name in ("converse", "review_converse"):
            # memory jobs are single completions; a tool loop would make calls
            # that bypass the counter, so the counted ask simply has no such method
            raise AttributeError(name)
        return getattr(self._ask, name)


def distiller(
    config: ExecutorConfig, *, store: Store | None = None
) -> EndpointReasoner | EndpointTextReasoner | CountedAsk:
    if config.reasoner == REASONER_HOST:
        raise ReasonerUnavailableError(HOST_REASONER_REMOVED)
    if config.reasoner == REASONER_ENDPOINT:
        endpoint = EndpointReasoner(
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            credentials=VertexCredentials(project=config.project, location=config.location),
            base_url=config.endpoint,
            key_env=config.key_env,
            attempts=config.attempts,
        )
        reasoner: EndpointReasoner | EndpointTextReasoner
        if config.tool_mode == TOOL_MODE_TEXT:
            reasoner = EndpointTextReasoner(endpoint)
        else:
            reasoner = endpoint
        return CountedAsk(reasoner, store) if store is not None else reasoner
    raise ReasonerUnavailableError(f"unsupported reasoner {config.reasoner!r}")
