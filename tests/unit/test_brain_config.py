"""Sandbox profile settings: the provider allowlist, and nothing else."""

from mnemobun.executor.agents.base import _merge_provider_settings


def test_provider_allowlist_crosses_but_plugins_do_not(tmp_path):
    (tmp_path / "config.yaml").write_text(
        '{"model_providers": {"openrouter": {"base_url": "https://x"}},'
        ' "plugins": {"memory": true}, "mcp_servers": {"real": 1}}',
        encoding="utf-8",
    )
    configured = {"mcp_servers": {"sandbox": True}}
    merged = _merge_provider_settings(configured, str(tmp_path))
    assert merged["model_providers"] == {"openrouter": {"base_url": "https://x"}}
    assert "plugins" not in merged
    assert merged["mcp_servers"] == {"sandbox": True}


def test_allowlist_never_crosses_into_sandbox_privacy():
    """plugins/skills/sessions/memory must never cross into the sandbox."""
    from mnemobun.executor.agents.base import PROVIDER_CONFIG_ALLOWLIST

    for forbidden in ("plugins", "skills", "sessions", "memory", "hooks"):
        assert forbidden not in PROVIDER_CONFIG_ALLOWLIST


def test_allowlist_without_real_config_is_noop(tmp_path):
    assert _merge_provider_settings({"a": 1}, str(tmp_path)) == {"a": 1}
    assert _merge_provider_settings({"a": 1}, "") == {"a": 1}


def test_allowlist_yaml_real_config(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "model_providers:\n  openrouter:\n    base_url: https://y\n"
        "skills:\n  - everything\n",
        encoding="utf-8",
    )
    merged = _merge_provider_settings({}, str(tmp_path))
    if "model_providers" in merged:  # pyyaml present
        assert merged["model_providers"]["openrouter"]["base_url"] == "https://y"
        assert "skills" not in merged
