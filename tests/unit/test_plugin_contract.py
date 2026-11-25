"""P14.16: plugin-contract regressions, each pinning a defect that shipped.

Every test here failed before the fix (verified against the real Hermes
loaders, not against the code's appearance).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN_INIT = REPO / "hermes-plugin" / "__init__.py"


@pytest.fixture()
def plugin_module():
    for pkg in ("core", "adapters", "executor", "mcp"):
        src = REPO / "packages" / pkg / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
    spec = importlib.util.spec_from_file_location("mnemobun_plugin_contract", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("mnemobun_plugin_contract", None)


def _home_with_store(plugin_module, tmp_path):
    """A home whose store exists - the production shape (created by mnemobun setup)."""
    home = tmp_path / "home"
    home.mkdir()
    provider = plugin_module.AgentMemoryHermesProvider()
    store_root = Path(provider._resolve_store_path(str(home)))
    store = plugin_module.Store(root=store_root)
    store.init()
    return home, store_root


def _flat_provider(plugin_module, tmp_path, monkeypatch=None, menu=None, effective=None):
    """Provider bound to a temp home/store with the host surfaces stubbed.

    ``menu`` is a list of (label, model-id) pairs, exactly as the host menu
    hands them over.
    """
    provider = plugin_module.AgentMemoryHermesProvider()
    provider._hermes_home = str(tmp_path)
    provider._store_path = str(tmp_path / "store")
    if monkeypatch is not None:
        monkeypatch.setattr(provider, "_model_menu", staticmethod(lambda: list(menu or [])))
        monkeypatch.setattr(provider, "_effective", lambda: dict(effective or {}))
        monkeypatch.setattr(provider, "_ensure_store", lambda *a, **k: True)
    return provider


def test_the_panel_offers_exactly_four_fields(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(plugin_module, tmp_path, monkeypatch)

    keys = [field["key"] for field in provider.get_config_schema()]

    assert keys == ["model", "max_calls_per_run", "max_tokens_per_day", "store_path"]


def test_the_model_field_offers_the_host_menu_with_unset_first(
    plugin_module, tmp_path, monkeypatch
):
    provider = _flat_provider(
        plugin_module,
        tmp_path,
        monkeypatch,
        menu=[("Nous Portal \u00b7 alpha", "alpha"), ("OpenRouter \u00b7 beta", "beta")],
    )

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert model["choices"] == ["", "Nous Portal \u00b7 alpha", "OpenRouter \u00b7 beta"]


def test_a_saved_model_outside_the_menu_joins_the_choices(
    plugin_module, tmp_path, monkeypatch
):
    provider = _flat_provider(
        plugin_module,
        tmp_path,
        monkeypatch,
        menu=[("Nous Portal \u00b7 alpha", "alpha")],
        effective={"model": "custom"},
    )

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert model["choices"] == ["", "Nous Portal \u00b7 alpha", "custom"]


def test_without_a_menu_the_model_field_stays_typed(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(plugin_module, tmp_path, monkeypatch, menu=[])

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert "choices" not in model


def test_field_defaults_come_from_the_store(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(
        plugin_module,
        tmp_path,
        monkeypatch,
        effective={"model": "m1", "max_calls_per_run": 7.0, "max_tokens_per_day": 999.0},
    )

    fields = {field["key"]: field["default"] for field in provider.get_config_schema()}

    assert fields["model"] == "m1"
    assert fields["max_calls_per_run"] == 7.0
    assert fields["max_tokens_per_day"] == 999.0


def test_save_refuses_a_model_the_providers_do_not_offer(
    plugin_module, tmp_path, monkeypatch
):
    provider = _flat_provider(
        plugin_module,
        tmp_path,
        monkeypatch,
        menu=[("Nous Portal \u00b7 alpha", "alpha")],
    )

    with pytest.raises(ValueError, match="not offered"):
        provider.save_config({"model": "not-in-menu"}, str(tmp_path))


def test_save_writes_the_store_and_nothing_else(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(
        plugin_module, tmp_path, monkeypatch, menu=[("Nous Portal \u00b7 alpha", "alpha")]
    )
    recorded: list = []
    monkeypatch.setattr(
        plugin_module,
        "apply_settings",
        lambda store, payload, actor: recorded.append((payload, actor)),
    )

    provider.save_config({"model": "Nous Portal \u00b7 alpha"}, str(tmp_path))

    assert recorded == [({"model": "alpha"}, "gui")]
    assert not (tmp_path / "mnemobun").exists()  # no mirror file


def test_the_ask_uses_the_recorded_model_and_refuses_without_one(
    plugin_module, tmp_path, monkeypatch
):
    provider = _flat_provider(plugin_module, tmp_path, monkeypatch)
    provider._store = object()
    calls: list = []

    class FakeResult:
        text = "reply"

    class FakeLlm:
        def complete(self, messages, **kwargs):
            calls.append(kwargs.get("model"))
            return FakeResult()

    monkeypatch.setattr(
        plugin_module, "effective_settings", lambda store: {"model": "alpha"}
    )
    monkeypatch.setattr(plugin_module, "provider", provider)
    ask = plugin_module._make_plugin_ask(FakeLlm())

    assert ask("hello") == "reply"
    assert calls == ["alpha"]

    monkeypatch.setattr(plugin_module, "effective_settings", lambda store: {"model": ""})
    with pytest.raises(Exception, match="no model configured"):
        ask("hello")


def test_get_config_schema_uses_the_host_key_contract(plugin_module):
    """Regression: the host normalizer reads field["key"] and silently drops
    fields without one - the panel then shows "does not expose dashboard
    settings" although the provider declares a schema."""
    fields = plugin_module.AgentMemoryHermesProvider().get_config_schema()

    assert fields, "the provider must declare settings"
    for field in fields:
        assert str(field.get("key") or "").strip(), f"field missing key: {field}"
    assert {field["key"] for field in fields} == {
        "model",
        "max_calls_per_run",
        "max_tokens_per_day",
        "store_path",
    }


def test_register_exposes_both_idle_tasks(plugin_module):
    """Regression: register() referenced provider.feed_tick, which did not
    exist - the feed idle task silently never registered since P13.5."""
    registered: dict = {}
    seen: dict = {}

    class Ctx:
        def register_memory_provider(self, provider):
            seen["provider"] = provider

        def register_idle_task(self, name, fn, **kwargs):
            assert callable(fn), name
            registered[name] = fn

    plugin_module.register(Ctx())

    assert sorted(registered) == ["dream", "feed"]
    assert seen["provider"] is plugin_module.provider


def test_feed_tick_is_callable_and_quiet_without_a_store(plugin_module, tmp_path):
    provider = plugin_module.AgentMemoryHermesProvider()
    assert callable(provider.feed_tick)
    provider._hermes_home = str(tmp_path / "nowhere")
    assert provider.feed_tick(None) is None


def test_save_config_refuses_loudly_when_the_store_is_missing(plugin_module, tmp_path):
    """Regression: writes were dropped in silence; the write contract says a
    save must be refused with ValueError."""
    home = tmp_path / "home"
    home.mkdir()
    provider = plugin_module.AgentMemoryHermesProvider()

    with pytest.raises(ValueError, match="store not found"):
        provider.write_config_fields({"model": "x"}, str(home))


def test_config_fields_honor_the_given_home_and_the_contract_shape(plugin_module, tmp_path):
    """Regression: store resolution ignored the hermes_home parameter (it fell
    back to the process home), and read_config_fields returned a flat dict
    where the host reads values+placeholders."""
    home, store_root = _home_with_store(plugin_module, tmp_path)
    provider = plugin_module.AgentMemoryHermesProvider()

    provider.write_config_fields({"model": "m-param"}, str(home))
    shape = provider.read_config_fields(str(home))
    assert set(shape) == {"values", "placeholders"}
    assert shape["values"]["model"] == "m-param"
    assert str(store_root).startswith(str(home))

    # values live on disk under the GIVEN home (fresh reopen)
    reopened = plugin_module.Store(root=store_root)
    assert reopened.config.executor.model == "m-param"

    # the write contract: an explicit None clears the key
    provider.write_config_fields({"model": None}, str(home))
    assert provider.read_config_fields(str(home))["values"]["model"] == ""
