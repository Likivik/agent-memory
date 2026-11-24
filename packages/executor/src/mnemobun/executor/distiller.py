"""The library-side distiller: the store's config names who reasons, the host CLI by default.

One extraction for every host (ADR-002 as amended). What is sent and what the reply may do
are decided in the core; this module only picks the pipe the text travels through. A host
whose dialect has an MCP posture runs as a tool-use agent over the Write toolkit; the rest
keep the text protocol.
"""

from __future__ import annotations

from mnemobun.core.config import (
    REASONER_ENDPOINT,
    REASONER_HOST,
    TOOL_MODE_TEXT,
    ExecutorConfig,
)
from mnemobun.core.errors import ReasonerUnavailableError

from .credentials import VertexCredentials
from .reasoners import EndpointReasoner, EndpointTextReasoner

HOST_REASONER_REMOVED = (
    "host reasoners were removed from memory jobs (2026-11-24): one completion is "
    "one call, and only a direct endpoint can be counted and bounded. configure one: "
    "mnemobun brain config write --endpoint <url> --key-env <env> --model <m>"
)


def distiller(config: ExecutorConfig) -> EndpointReasoner | EndpointTextReasoner:
    if config.reasoner == REASONER_HOST:
        raise ReasonerUnavailableError(HOST_REASONER_REMOVED)
    if config.reasoner == REASONER_ENDPOINT:
        endpoint = EndpointReasoner(
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            credentials=VertexCredentials(project=config.project, location=config.location),
            base_url=config.endpoint,
            attempts=config.attempts,
        )
        if config.tool_mode == TOOL_MODE_TEXT:
            return EndpointTextReasoner(endpoint)
        return endpoint
    raise ReasonerUnavailableError(f"unsupported reasoner {config.reasoner!r}")
