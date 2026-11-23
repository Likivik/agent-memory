"""Explicit model resolution with provenance (user ruling: never silent).

The model comes only from a place the user set — a per-run flag, the brain
config (chat/CLI setup), or the GUI field. Nothing is inherited from the
gateway and no default exists; when nothing resolves, callers get ``None``
and must run deterministic-only with the loud needs-model message.
"""

from __future__ import annotations

import dataclasses

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
    """flag > brain config > gui field > None. Never a default."""
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
    """Record the model and where it came from. Single write path."""
    if source not in SET_SOURCES:
        raise ValueError(f"model source must be one of {SET_SOURCES}, got {source!r}")
    brain = store.config.executor
    brain.host_model = model.strip()
    brain.model_source = source
    store.config.save(store.root)
    return ModelRoute(model.strip(), source)


def sync_gui_config(store: Store, gui: dict[str, str]) -> dict[str, object]:
    """Write-once import of GUI fields: fill empty brain fields, never overwrite.

    Restart-safe: once any surface sets a value, the store config owns it and
    later GUI syncs leave it alone (the 2026-11-24 revert ruling).
    """
    imported: dict[str, str] = {}
    skipped: dict[str, str] = {}
    brain = store.config.executor
    if gui.get("model", "").strip():
        if brain.host_model or brain.model:
            skipped["model"] = brain.host_model or brain.model
        else:
            route = set_model(store, gui["model"], SOURCE_GUI)
            imported["model"] = route.model
    for key, attribute in (("distill_model", "write"), ("dream_model", "manage")):
        value = gui.get(key, "").strip()
        if not value:
            continue
        policy = getattr(brain, attribute)
        if policy.model:
            skipped[key] = policy.model
        else:
            policy.model = value
            imported[key] = value
    if imported:
        store.config.save(store.root)
    return {"imported": imported, "skipped": skipped}
