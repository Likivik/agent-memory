"""Resolve one operation's reasoner policy without changing what the operation does."""

from __future__ import annotations

import dataclasses

from mnemobun.core.config import (
    REASONER_DIALECTS,
    REASONER_PLUGIN,
    ExecutorConfig,
    OperationExecutorConfig,
)
from mnemobun.core.errors import ReasonerUnavailableError

WRITE = "write"
MANAGE = "manage"
OPERATIONS = (WRITE, MANAGE)

def resolve(
    config: ExecutorConfig,
    operation: str,
    *,
    reasoner: str = "",
    model: str = "",
) -> ExecutorConfig:
    """Merge the operation policy over the executor policy. A CLI dialect or
    "plugin" only; anything else fails here, loudly."""
    if operation not in OPERATIONS:
        raise ReasonerUnavailableError(f"unsupported memory operation: {operation}")
    policy: OperationExecutorConfig = getattr(config, operation)
    chosen = dataclasses.replace(
        config,
        reasoner=policy.reasoner or config.reasoner,
        timeout_seconds=policy.timeout_seconds or config.timeout_seconds,
    )
    if reasoner:
        chosen = dataclasses.replace(chosen, reasoner=reasoner)
    if model:
        chosen = dataclasses.replace(chosen, model=model)
    if chosen.reasoner != REASONER_PLUGIN and chosen.reasoner not in REASONER_DIALECTS:
        raise ReasonerUnavailableError(
            f"unsupported reasoner {chosen.reasoner!r} for {operation}"
        )
    return chosen
