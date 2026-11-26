"""The library-side distiller: the store's config names who reasons, the host CLI by default.

One extraction for every host (ADR-002 as amended). What is sent and what the reply may do
are decided in the core; this module only picks the pipe the text travels through. A host
whose transport has an MCP posture runs as a tool-use agent over the Write toolkit; the rest
keep the text protocol.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from mnemobun.core.config import ExecutorConfig
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.core.store import Store


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
    config: ExecutorConfig,
    *,
    store: Store | None = None,
    ask: Callable[[str], str] | None = None,
) -> Callable[[str], str]:
    """The counted ask for memory jobs: the caller's reasoner, never config-built.

    The host CLI supplies a ``DriverReasoner``; the Hermes plugin supplies its
    ``ctx.llm`` adapter. Nothing here reaches the network on its own.
    """
    if ask is None:
        raise ReasonerUnavailableError(
            "no reasoner configured: supply a driver reasoner or the plugin LLM "
            f"(executor reasoner {config.reasoner!r})"
        )
    return CountedAsk(ask, store) if store is not None else ask
