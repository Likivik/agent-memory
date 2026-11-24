"""Explicit model resolution with provenance (user ruling: never silent).

The model comes only from a place the user set — a per-run flag or the store
settings written through ``mnemobun.core.settings.apply_settings``. Nothing is
inherited from the gateway and no default exists; when nothing resolves,
callers get ``None`` and must run deterministic-only with the loud
needs-model message.
"""

from __future__ import annotations

import dataclasses

from mnemobun.core import settings
from mnemobun.core.store import Store

SOURCE_FLAG = "flag"
SOURCE_CHAT = "chat"
SOURCE_CLI = "cli"
SOURCE_GUI = "gui"
SOURCE_UNSET = "unset"
SET_SOURCES = (SOURCE_CHAT, SOURCE_CLI, SOURCE_GUI)

NEEDS_MODEL = "no model configured (deterministic-only); set memory.model"


@dataclasses.dataclass(frozen=True)
class ModelRoute:
    model: str
    source: str

    def label(self) -> str:
        return f"{self.model} (source: {self.source})"


def resolve_model(
    *,
    flag: str = "",
    brain_model: str = "",
    brain_source: str = "",
    gui_model: str = "",
) -> ModelRoute | None:
    """flag > store settings > explicit gui field > None. Never a default."""
    if flag.strip():
        return ModelRoute(flag.strip(), SOURCE_FLAG)
    if brain_model.strip():
        return ModelRoute(brain_model.strip(), brain_source or SOURCE_UNSET)
    if gui_model.strip():
        return ModelRoute(gui_model.strip(), SOURCE_GUI)
    return None


def brain_model(store: Store) -> str:
    """The explicitly configured model on the brain (host or endpoint form)."""
    brain = store.config.executor
    return brain.host_model or brain.model


def route_for(store: Store, *, flag: str = "", gui_model: str = "") -> ModelRoute | None:
    return resolve_model(
        flag=flag,
        brain_model=brain_model(store),
        brain_source=store.config.executor.model_source,
        gui_model=gui_model,
    )


def set_model(store: Store, model: str, source: str) -> ModelRoute:
    """Compatibility wrapper: single-field write through the one writer."""
    if source not in SET_SOURCES:
        raise ValueError(f"model source must be one of {SET_SOURCES}, got {source!r}")
    settings.apply_settings(store, {"model": model}, actor=source)
    return ModelRoute(model.strip(), source)
