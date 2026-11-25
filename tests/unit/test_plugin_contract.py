"""P14.16: plugin-contract regressions, each pinning a defect that shipped.

Every test here failed before the fix (verified against the real Hermes
loaders, not against the code's appearance).
"""

from __future__ import annotations

import importlib.util
import json
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


def _flat_provider(plugin_module, tmp_path):
    """Provider bound to a temp home/store - no engine work involved."""
    provider = plugin_module.AgentMemoryHermesProvider()
    provider._hermes_home = str(tmp_path)
    provider._store_path = str(tmp_path / "store")
    return provider


def test_model_choices_come_from_the_cached_endpoint_models(plugin_module, tmp_path):
    provider = _flat_provider(plugin_module, tmp_path)
    (tmp_path / "store" / ".state").mkdir(parents=True)
    (tmp_path / "store" / ".state" / "models.json").write_text(
        json.dumps({"models": ["alpha", "beta"]}), encoding="utf-8"
    )

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert model["choices"] == ["", "alpha", "beta"]


def test_model_choices_keep_a_saved_value_outside_the_list(plugin_module, tmp_path):
    """A select cannot hold values outside its options - a saved model the
    cache lacks joins the list or the panel would show a different model."""
    provider = _flat_provider(plugin_module, tmp_path)
    (tmp_path / "store" / ".state").mkdir(parents=True)
    (tmp_path / "store" / ".state" / "models.json").write_text(
        json.dumps({"models": ["alpha"]}), encoding="utf-8"
    )
    (tmp_path / "mnemobun").mkdir()
    (tmp_path / "mnemobun" / "config.json").write_text(
        json.dumps({"model": "custom-model"}), encoding="utf-8"
    )

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert model["choices"] == ["", "alpha", "custom-model"]


def test_model_field_falls_back_to_typing_without_a_cached_list(plugin_module, tmp_path):
    provider = _flat_provider(plugin_module, tmp_path)

    model = next(f for f in provider.get_config_schema() if f["key"] == "model")

    assert "choices" not in model


def test_save_mirrors_settings_for_the_host_display_reader(plugin_module, tmp_path, monkeypatch):
    """The deployed dashboard's GET reads only $HERMES_HOME/<name>/config.json;
    settings kept just in the store would render as blank fields."""
    provider = _flat_provider(plugin_module, tmp_path)
    monkeypatch.setattr(provider, "_ensure_store", lambda *a, **k: True)
    monkeypatch.setattr(plugin_module, "apply_settings", lambda *a, **k: None)
    monkeypatch.setattr(
        plugin_module.AgentMemoryHermesProvider, "_probe_models",
        staticmethod(lambda _e, _k: ([], "")),
    )

    provider.save_config({"model": "m1", "endpoint": "https://x.example/v1"}, str(tmp_path))

    mirror = json.loads((tmp_path / "mnemobun" / "config.json").read_text(encoding="utf-8"))
    assert mirror["model"] == "m1"
    assert mirror["endpoint"] == "https://x.example/v1"


def test_save_refuses_a_malformed_endpoint(plugin_module, tmp_path):
    provider = _flat_provider(plugin_module, tmp_path)

    with pytest.raises(ValueError, match="not an http"):
        provider.save_config({"endpoint": "not a url"}, str(tmp_path))


def test_save_refreshes_the_model_cache_with_one_probe(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(plugin_module, tmp_path)
    monkeypatch.setattr(provider, "_ensure_store", lambda *a, **k: True)
    monkeypatch.setattr(plugin_module, "apply_settings", lambda *a, **k: None)
    calls: list = []

    def fake_probe(endpoint, key_env):
        calls.append((endpoint, key_env))
        return ["alpha", "beta"], ""

    monkeypatch.setattr(
        plugin_module.AgentMemoryHermesProvider, "_probe_models", staticmethod(fake_probe)
    )

    provider.save_config({"endpoint": "https://x.example/v1", "key_env": "X_KEY"}, str(tmp_path))

    assert calls == [("https://x.example/v1", "X_KEY")]
    model = next(f for f in provider.get_config_schema() if f["key"] == "model")
    assert model["choices"] == ["", "alpha", "beta"]


def test_save_survives_a_failed_model_probe(plugin_module, tmp_path, monkeypatch):
    provider = _flat_provider(plugin_module, tmp_path)
    monkeypatch.setattr(provider, "_ensure_store", lambda *a, **k: True)
    monkeypatch.setattr(plugin_module, "apply_settings", lambda *a, **k: None)
    monkeypatch.setattr(
        plugin_module.AgentMemoryHermesProvider, "_probe_models",
        staticmethod(lambda _e, _k: ([], "URLError: down")),
    )

    provider.save_config({"model": "m1", "endpoint": "https://x.example/v1"}, str(tmp_path))

    mirror = json.loads((tmp_path / "mnemobun" / "config.json").read_text(encoding="utf-8"))
    assert mirror["model"] == "m1"


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
        "endpoint",
        "key_env",
        "distill_model",
        "dream_model",
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

    provider.write_config_fields(
        {"model": "m-param", "endpoint": "https://models.example/v1"}, str(home)
    )
    shape = provider.read_config_fields(str(home))
    assert set(shape) == {"values", "placeholders"}
    assert shape["values"]["model"] == "m-param"
    assert shape["values"]["endpoint"] == "https://models.example/v1"
    assert str(store_root).startswith(str(home))

    # values live on disk under the GIVEN home (fresh reopen)
    reopened = plugin_module.Store(root=store_root)
    assert reopened.config.executor.model == "m-param"

    # the write contract: an explicit None clears the key
    provider.write_config_fields({"model": None}, str(home))
    assert provider.read_config_fields(str(home))["values"]["model"] == ""
