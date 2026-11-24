"""Resolve one operation's reasoner policy without changing what the operation does."""

from __future__ import annotations

import dataclasses

from mnemobun.core.config import (
    REASONER_ENDPOINT,
    TOOL_MODE_AUTO,
    TOOL_MODE_TEXT,
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
    """Merge the operation policy over the executor policy. Endpoint only;
    anything else fails here, loudly."""
    if operation not in OPERATIONS:
        raise ReasonerUnavailableError(f"unsupported memory operation: {operation}")
    policy: OperationExecutorConfig = getattr(config, operation)
    chosen = dataclasses.replace(
        config,
        reasoner=policy.reasoner or config.reasoner,
        model=policy.model or config.model,
        endpoint=policy.endpoint or config.endpoint,
        project=policy.project or config.project,
        location=policy.location or config.location,
        timeout_seconds=policy.timeout_seconds or config.timeout_seconds,
        tool_mode=(policy.tool_mode or config.tool_mode)
        if operation == WRITE
        else (policy.tool_mode or TOOL_MODE_TEXT),
    )
    if reasoner:
        chosen = dataclasses.replace(chosen, reasoner=reasoner)
    if model:
        chosen = dataclasses.replace(chosen, model=model)
    if chosen.reasoner not in (REASONER_ENDPOINT,):
        raise ReasonerUnavailableError(
            f"unsupported reasoner {chosen.reasoner!r} for {operation}"
        )
    if operation == WRITE and chosen.tool_mode not in ("", TOOL_MODE_AUTO, TOOL_MODE_TEXT):
        raise ReasonerUnavailableError("endpoint writes run auto or text tool modes")
    if operation == MANAGE and chosen.tool_mode not in ("", TOOL_MODE_TEXT):
        raise ReasonerUnavailableError("endpoint manage runs need text-only tool mode")
    return chosen
