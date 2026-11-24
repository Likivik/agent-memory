"""Model is never selected silently; ONE writer serves every surface (2026-11-24 rulings)."""

import json

import pytest
from mnemobun.core.config import Config
from mnemobun.core.settings import apply_settings, effective_settings
from mnemobun.core.store import Store
from mnemobun.executor.model_resolution import (
    NEEDS_MODEL,
    resolve_model,
    route_for,
    set_model,
)
from mnemobun.mcp.tools import dispatch


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    return store


def test_no_silent_defaults_anywhere():
    executor = Config.default().executor
    assert executor.model == ""
    assert executor.model == ""
    assert executor.model_source == "unset"
    assert Config.default().budget.max_calls_per_run > 0


def test_resolution_precedence_flag_brain_gui_then_none():
    assert resolve_model(flag="f", brain_model="b", gui_model="g").source == "flag"
    route = resolve_model(brain_model="b", brain_source="chat", gui_model="g")
    assert route.label() == "b (source: chat)"
    assert resolve_model(gui_model="g").source == "gui"
    assert resolve_model() is None
    assert resolve_model(brain_model="   ") is None
    assert "set memory.model" in NEEDS_MODEL


def test_one_writer_all_actors_produce_identical_state(tmp_path):
    for actor in ("chat", "cli", "gui"):
        store = _store(tmp_path / actor)
        apply_settings(
            store,
            {"model": "m1", "distill_model": "d1", "dream_model": "r1",
             "max_calls_per_run": 7, "max_tokens_per_day": 1000},
            actor=actor,
        )
        settings = effective_settings(store)
        assert settings["model"] == "m1"
        assert settings["model_source"] == actor
        assert settings["distill_model"] == "d1"
        assert settings["max_calls_per_run"] == 7.0
        reloaded = Store(store.root, config=Config.load(store.root), agent="t")
        assert route_for(reloaded).label() == f"m1 (source: {actor})"


def test_endpoint_and_key_env_are_settings_not_side_channels(tmp_path):
    from mnemobun.core.config import Config
    from mnemobun.core.settings import apply_settings, effective_settings
    from mnemobun.core.store import Store

    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    apply_settings(
        store,
        {"endpoint": "https://api.example.test/v1", "key_env": "MY_KEY"},
        actor="gui",
    )
    settings = effective_settings(store)
    assert settings["endpoint"] == "https://api.example.test/v1"
    assert settings["key_env"] == "MY_KEY"
    assert store.config.executor.reasoner == "endpoint"


def test_the_settings_model_reaches_the_endpoint_reasoner(tmp_path):
    from mnemobun.core.config import Config
    from mnemobun.core.settings import apply_settings
    from mnemobun.core.store import Store
    from mnemobun.executor import distiller, selection

    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    apply_settings(
        store,
        {"model": "mimo", "endpoint": "https://x.test/v1", "key_env": "K"},
        actor="gui",
    )
    config = selection.resolve(store.config.executor, "write")
    built = distiller.distiller(config, store=store)
    inner = getattr(built, "_ask", built)
    assert inner.model == "mimo"
    assert inner.base_url == "https://x.test/v1"


def test_the_counted_ask_hides_converse_so_no_uncounted_loop_can_start():
    from mnemobun.executor.distiller import CountedAsk

    class Fake:
        def __call__(self, prompt: str) -> str:
            return "{}"

        def converse(self, *args: object) -> None:
            raise AssertionError("must never be reached through the counted ask")

    counted = CountedAsk(Fake(), store=None)  # type: ignore[arg-type]
    assert not hasattr(counted, "converse")
    assert not hasattr(counted, "review_converse")


def test_apply_settings_validates(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        apply_settings(store, {"telepathy": "x"}, actor="gui")
    with pytest.raises(ValueError):
        apply_settings(store, {"model": "  "}, actor="gui")
    with pytest.raises(ValueError):
        apply_settings(store, {"max_calls_per_run": -1}, actor="gui")
    assert effective_settings(store)["model"] == ""


def test_audit_records_change_and_actor(tmp_path):
    store = _store(tmp_path)
    apply_settings(store, {"model": "m1"}, actor="gui")
    apply_settings(store, {"model": "m2"}, actor="chat")
    lines = (store.root / ".state" / "settings-audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["actor"] == "gui"
    assert first["changed"]["model"] == {"from": "", "to": "m1"}
    assert second["actor"] == "chat"
    # a no-op write records nothing
    apply_settings(store, {"model": "m2"}, actor="cli")
    assert len((store.root / ".state" / "settings-audit.jsonl").read_text().splitlines()) == 2


def test_mcp_memory_setup_routes_through_the_writer(tmp_path):
    store = _store(tmp_path)
    dispatch(store, "memory_setup", {"model": "chat-model"})
    assert route_for(store).label() == "chat-model (source: chat)"
    lines = (store.root / ".state" / "settings-audit.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["actor"] == "chat"


def test_set_model_is_a_wrapper(tmp_path):
    store = _store(tmp_path)
    route = set_model(store, "m1", "cli")
    assert route.label() == "m1 (source: cli)"
    assert effective_settings(store)["model_source"] == "cli"
