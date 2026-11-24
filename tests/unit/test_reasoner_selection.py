import dataclasses

import pytest
from mnemobun.core.config import (
    TOOL_MODE_NATIVE,
    TOOL_MODE_TEXT,
    Config,
    OperationExecutorConfig,
)
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.executor import distiller, selection
from mnemobun.executor.reasoners import EndpointTextReasoner


def test_default_write_uses_the_source_host_while_manage_uses_the_legacy_executor():
    executor = Config.default().executor

    write = selection.resolve(executor, selection.WRITE, source_host="muse-code")
    manage = selection.resolve(executor, selection.MANAGE, source_host="muse-code")

    assert write.reasoner == "host"
    assert write.host == "muse-code"
    assert manage.reasoner == "host"
    assert manage.host == "claude-code"


def test_operation_policies_select_independent_hosts_without_source_override():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(reasoner="host", host="muse-code")
    executor.manage = OperationExecutorConfig(reasoner="host", host="codex")

    write = selection.resolve(executor, selection.WRITE, source_host="codex")
    manage = selection.resolve(executor, selection.MANAGE, source_host="muse-code")

    assert write.host == "muse-code"
    assert manage.host == "codex"


def test_host_policies_are_refused_and_endpoint_policies_build():
    import pytest
    from mnemobun.core.config import Config
    from mnemobun.core.errors import ReasonerUnavailableError
    from mnemobun.executor import distiller

    config = Config.default().executor
    config.reasoner = "endpoint"
    config.endpoint = "https://example.test/v1"
    config.model = "m"
    config.write.model = "m"
    built = distiller.distiller(selection.resolve(config, selection.WRITE))
    assert type(built).__name__ in ("EndpointReasoner", "EndpointTextReasoner")

    host = Config.default().executor
    host.reasoner = "host"
    host.host = "hermes"
    with pytest.raises(ReasonerUnavailableError):
        distiller.distiller(selection.resolve(host, selection.WRITE))


def test_operation_host_provider_overrides_the_legacy_provider():
    executor = Config.default().executor
    executor.host_provider = "gemini"
    executor.write = OperationExecutorConfig(
        reasoner="host", host="hermes", host_provider="openrouter"
    )

    write = selection.resolve(executor, selection.WRITE)
    manage = selection.resolve(executor, selection.MANAGE)

    assert write.host_provider == "openrouter"
    assert manage.host_provider == "gemini"


def test_data_training_consent_is_explicit_and_operation_scoped():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(
        reasoner="host",
        host="hermes",
        host_provider="openrouter",
        host_allow_data_training=True,
    )

    write = selection.resolve(executor, selection.WRITE)
    manage = selection.resolve(executor, selection.MANAGE)

    assert write.host_allow_data_training is True
    assert manage.host_allow_data_training is False


def test_source_is_an_explicit_write_host_policy_but_is_invalid_for_manage():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(reasoner="host", host="source")
    executor.manage = OperationExecutorConfig(reasoner="host", host="source")

    assert selection.resolve(executor, selection.WRITE, source_host="codex").host == "codex"
    with pytest.raises(ReasonerUnavailableError, match="manage reasoner host cannot be source"):
        selection.resolve(executor, selection.MANAGE, source_host="muse-code")


def test_operation_endpoint_fields_fall_back_to_legacy_endpoint_fields_individually():
    executor = Config.default().executor
    executor.reasoner = "endpoint"
    executor.endpoint = "https://legacy.example/v1"
    executor.project = "legacy-project"
    executor.manage = OperationExecutorConfig(
        reasoner="endpoint", endpoint="https://manage.example/v1", model="manage-model"
    )

    write = selection.resolve(executor, selection.WRITE, source_host="codex")
    manage = selection.resolve(executor, selection.MANAGE)

    assert write.reasoner == "endpoint"
    assert write.endpoint == "https://legacy.example/v1"
    assert manage.endpoint == "https://manage.example/v1"
    assert manage.model == "manage-model"
    assert manage.project == "legacy-project"


def test_explicit_cli_fields_override_only_the_selected_operation_policy():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(
        reasoner="endpoint", endpoint="https://write.example/v1", model="write-model"
    )

    chosen = selection.resolve(
        executor,
        selection.WRITE,
        source_host="muse-code",
        reasoner="host",
        host="codex",
        model="cli-model",
    )

    assert chosen.reasoner == "host"
    assert chosen.host == "codex"
    assert chosen.host_model == "cli-model"


def test_unknown_reasoner_fails_closed_instead_of_becoming_a_host():
    configured = dataclasses.replace(Config.default().executor, reasoner="surprise")

    with pytest.raises(ReasonerUnavailableError, match="unsupported reasoner"):
        distiller.distiller(configured)


def test_manage_native_mode_rejects_endpoint_and_unverified_hosts():
    executor = Config.default().executor
    executor.manage = OperationExecutorConfig(reasoner="endpoint", tool_mode=TOOL_MODE_NATIVE)
    with pytest.raises(ReasonerUnavailableError, match="requires a host"):
        selection.resolve(executor, selection.MANAGE)

    executor.manage = OperationExecutorConfig(
        reasoner="host", host="unverified-host", tool_mode=TOOL_MODE_NATIVE
    )
    with pytest.raises(
        ReasonerUnavailableError, match="supports only claude-code, codex, hermes, muse-code"
    ):
        selection.resolve(executor, selection.MANAGE)


def test_endpoint_write_text_mode_routes_through_the_line_protocol():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(reasoner="endpoint", tool_mode=TOOL_MODE_TEXT)

    reasoner = distiller.distiller(selection.resolve(executor, selection.WRITE))
    assert isinstance(reasoner, EndpointTextReasoner)
