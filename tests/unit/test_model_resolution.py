"""Model is never selected silently; provenance is recorded (2026-11-24 rulings)."""

import pytest
from mnemobun.core.config import Config
from mnemobun.core.store import Store
from mnemobun.executor.model_resolution import (
    NEEDS_MODEL,
    resolve_model,
    route_for,
    set_model,
    sync_gui_config,
)


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    return store


def test_no_silent_defaults_anywhere():
    executor = Config.default().executor
    assert executor.model == ""
    assert executor.host_model == ""
    assert executor.model_source == "unset"


def test_resolution_precedence_flag_brain_gui_then_none():
    assert resolve_model(flag="f", brain_model="b", gui_model="g").source == "flag"
    route = resolve_model(brain_model="b", brain_source="chat", gui_model="g")
    assert route.label() == "b (source: chat)"
    assert resolve_model(gui_model="g").source == "gui"
    assert resolve_model() is None
    assert resolve_model(brain_model="   ") is None
    assert "set memory.model" in NEEDS_MODEL


def test_set_model_records_source_and_rejects_unknown(tmp_path):
    store = _store(tmp_path)
    route = set_model(store, "m1", "chat")
    assert route.label() == "m1 (source: chat)"
    assert route_for(store).label() == "m1 (source: chat)"
    with pytest.raises(ValueError):
        set_model(store, "m2", "telepathy")
    reloaded = Store(store.root, config=Config.load(store.root), agent="t")
    assert route_for(reloaded).label() == "m1 (source: chat)"


def test_gui_sync_is_write_once(tmp_path):
    store = _store(tmp_path)
    first = sync_gui_config(store, {"model": "gui-model"})
    assert first["imported"] == {"model": "gui-model"}
    second = sync_gui_config(store, {"model": "other-model"})
    assert second["skipped"] == {"model": "gui-model"}
    assert route_for(store).label() == "gui-model (source: gui)"
    # chat sets it afterwards; a later restart sync must not revert it
    set_model(store, "chat-model", "chat")
    third = sync_gui_config(store, {"model": "gui-again"})
    assert third["skipped"] == {"model": "chat-model"}
    assert route_for(store).label() == "chat-model (source: chat)"


def test_gui_sync_fills_empty_policy_models(tmp_path):
    store = _store(tmp_path)
    result = sync_gui_config(
        store, {"distill_model": "d1", "dream_model": "r1"}
    )
    assert result["imported"] == {"distill_model": "d1", "dream_model": "r1"}
    assert store.config.executor.write.model == "d1"
    assert store.config.executor.manage.model == "r1"
