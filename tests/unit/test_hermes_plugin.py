"""P10 HP1/HP2/HP3/HP4: the vendored Hermes plugin adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN_INIT = REPO / "hermes-plugin" / "__init__.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("mnemobun_hermes_plugin", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def plugin_module():
    # hermes-plugin/lib may not exist in a fresh checkout; point sys.path at the
    # workspace packages so the plugin's imports resolve the same way.
    for pkg in ("core", "adapters", "executor", "mcp"):
        src = REPO / "packages" / pkg / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
    mod = _load_plugin_module()
    yield mod
    sys.modules.pop("mnemobun_hermes_plugin", None)


@pytest.fixture()
def provider(plugin_module, tmp_path):
    p = plugin_module.AgentMemoryHermesProvider()
    p._resolve_store_path = lambda home=None: tmp_path / "store"  # type: ignore[method-assign]
    return p


def _store_ready(provider, tmp_path):
    (tmp_path / "store").mkdir(parents=True, exist_ok=True)
    assert provider._ensure_store() is True
    return provider._store


def _write(store, name, abstract):
    store.record(name=name, abstract=abstract, type="fact")


# -- HP2: lifecycle -------------------------------------------------------


def test_initialize_is_idempotent_and_lazy(provider, tmp_path):
    (tmp_path / "store").mkdir()
    for _ in range(100):
        assert provider.initialize("sess-1", hermes_home=str(tmp_path)) is True
    assert provider.is_available() is True
    assert provider.name == "mnemobun"
    assert provider.identity_signature()["provider"] == "mnemobun"


def test_is_available_false_when_store_missing(provider, tmp_path):
    assert provider.initialize("sess-1", hermes_home=str(tmp_path)) is False
    assert "unavailable" in provider.unavailable_reason() or provider.unavailable_reason()


def test_prefetch_respects_budget(provider, tmp_path):
    store = _store_ready(provider, tmp_path)
    for i in range(30):
        _write(store, f"fact-{i:02d}", "x" * 120)
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    text = provider.prefetch("anything")
    assert len(text.encode("utf-8")) <= provider._store.config.provider.prefetch_budget_bytes


def test_sync_turn_writes_one_event(provider, tmp_path):
    store = _store_ready(provider, tmp_path)
    provider.initialize("sess-9", hermes_home=str(tmp_path))
    provider.sync_turn("hello", "hi there", session_id="sess-9")
    provider.sync_turn("", "", session_id="sess-9")  # empty turn: no record
    events = [r for r in store.records() if r.type == "event"]
    assert len(events) == 1
    assert events[0].name.startswith("turn-sess-9-")


def test_recall_status_counts_lines(provider, tmp_path):
    store = _store_ready(provider, tmp_path)
    _write(store, "fact-a", "something real to recall")
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    provider.prefetch("something real")
    status = provider.recall_status()
    assert status.provider_label == "mnemobun"
    assert status.count >= 1


# -- HP3: tool surface ------------------------------------------------------


def test_tool_schemas_and_dispatch(provider, tmp_path):
    store = _store_ready(provider, tmp_path)
    _write(store, "fact-a", "something real")
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    schemas = provider.get_tool_schemas()
    assert {s["name"] for s in schemas} >= {"memory_recall", "memory_record", "memory_stats"}
    out = json.loads(provider.handle_tool_call("memory_stats", {}))
    assert out["by_type"]["fact"] == 1


def test_unknown_tool_returns_error_shape(provider, tmp_path):
    provider._ensure_store()
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    out = json.loads(provider.handle_tool_call("memory_nope", {}))
    assert "error" in out


# -- HP4: dream tick ----------------------------------------------------------


def test_dream_tick_skips_when_not_due(provider, tmp_path):
    _store_ready(provider, tmp_path)
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    assert provider.dream_tick(type("R", (), {"run_count": 0})()) is None


def test_dream_tick_runs_deterministic_sleep_when_due(provider, tmp_path, monkeypatch):
    _store_ready(provider, tmp_path)
    provider.initialize("sess-1", hermes_home=str(tmp_path))
    import mnemobun.core.manage as manage_mod

    monkeypatch.setattr(manage_mod.Manage, "due", lambda self, sessions_since: sessions_since >= 3)
    ran = []
    monkeypatch.setattr(
        manage_mod.Manage,
        "sleep",
        lambda self, reasoner=None, *, dream_id="": (
            ran.append(dream_id) or type("R", (), {"as_dict": lambda s: {"actions": []}})()
        ),
    )
    result = provider.dream_tick(type("R", (), {"run_count": 5})())
    assert result is not None
    assert ran == [""]
    # idempotent: repeated polls keep queueing nothing extra
    provider.dream_tick(type("R", (), {"run_count": 5})())
    assert len(ran) == 2


# -- HP1: vendored lib present -------------------------------------------------


def test_vendored_lib_exists():
    lib = REPO / "hermes-plugin" / "lib"
    assert (lib / "mnemobun" / "core" / "store.py").exists()
    assert (lib / "mnemobun" / "mcp" / "tools.py").exists()
