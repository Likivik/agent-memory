"""Route resolution: a pair, or a named reason not to have one."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from mnemobun.core.specs import (
    STATE_RESOLVED,
    STATE_UNAVAILABLE,
    STATE_UNSET,
    STATE_VANISHED,
    Route,
    RouteState,
)

Catalogue = Callable[[], Iterable[tuple[str, str]]]


def resolve_route(store: Any, catalogue: Catalogue | None) -> RouteState:
    """Stored pair against the current catalogue. Never guesses, never caches."""
    route = Route(
        provider=str(store.config.executor.provider or ""),
        model=str(store.config.executor.model or ""),
    )
    if not route.is_set:
        return RouteState(STATE_UNSET, route, "no route configured (deterministic-only)")
    if catalogue is None:
        return RouteState(STATE_UNAVAILABLE, route, "model menu unavailable")
    try:
        pairs = {(str(p), str(m)) for p, m in catalogue()}
    except Exception:
        return RouteState(STATE_UNAVAILABLE, route, "model menu unavailable")
    if not pairs:
        return RouteState(STATE_UNAVAILABLE, route, "model menu unavailable")
    if (route.provider, route.model) not in pairs:
        return RouteState(
            STATE_VANISHED, route, f"no route configured: '{route.label()}' is no longer offered"
        )
    return RouteState(STATE_RESOLVED, route)
