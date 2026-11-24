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
