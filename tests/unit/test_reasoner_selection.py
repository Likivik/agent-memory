"""Reasoner policy for memory jobs: endpoint only, loud refusals otherwise."""

from __future__ import annotations

import dataclasses

import pytest
from mnemobun.core.config import (
    TOOL_MODE_AUTO,
    TOOL_MODE_TEXT,
    Config,
    OperationExecutorConfig,
)
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.executor import distiller, selection
from mnemobun.executor.reasoners import EndpointTextReasoner


def test_write_merges_the_operation_policy_over_the_executor_policy():
    executor = Config.default().executor
    executor.model = "base-model"
    executor.endpoint = "https://base.example/v1"
    executor.write = OperationExecutorConfig(model="write-model", timeout_seconds=7.0)

    write = selection.resolve(executor, selection.WRITE)

    assert write.model == "write-model"
    assert write.endpoint == "https://base.example/v1"  # per-field fallback
    assert write.timeout_seconds == 7.0


def test_manage_defaults_to_text_tool_mode():
    executor = Config.default().executor
    executor.model = "base-model"

    assert selection.resolve(executor, selection.MANAGE).tool_mode == TOOL_MODE_TEXT


def test_operation_policies_select_independent_models():
    executor = Config.default().executor
    executor.write = OperationExecutorConfig(
        reasoner="endpoint", model="write-model"
    )
    executor.manage = OperationExecutorConfig(
        reasoner="endpoint", model="manage-model"
    )

    write = selection.resolve(executor, selection.WRITE)
    manage = selection.resolve(executor, selection.MANAGE)

    assert write.model == "write-model"
    assert manage.model == "manage-model"


def test_unknown_reasoners_are_refused_and_endpoint_policies_build():
    config = Config.default().executor
    config.reasoner = "endpoint"
    config.endpoint = "https://example.test/v1"
    config.model = "m"
    config.write.model = "m"
    built = distiller.distiller(selection.resolve(config, selection.WRITE))
    assert type(built).__name__ in ("EndpointReasoner", "EndpointTextReasoner")

    host = Config.default().executor
    host.reasoner = "host"
    host.model = "m"
    with pytest.raises(ReasonerUnavailableError):
        distiller.distiller(selection.resolve(host, selection.WRITE))


def test_an_unknown_reasoner_override_is_refused():
    executor = Config.default().executor
    executor.model = "m"
    with pytest.raises(ReasonerUnavailableError):
        selection.resolve(executor, selection.WRITE, reasoner="surprise")


def test_operation_endpoint_fields_fall_back_to_legacy_endpoint_fields_individually():
    executor = Config.default().executor
    executor.reasoner = "endpoint"
    executor.endpoint = "https://legacy.example/v1"
    executor.project = "legacy-project"
    executor.model = "write-model"
    executor.manage = OperationExecutorConfig(
        reasoner="endpoint", endpoint="https://manage.example/v1", model="manage-model"
    )

    write = selection.resolve(executor, selection.WRITE)
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
    executor.manage = OperationExecutorConfig(
        reasoner="endpoint", model="manage-model"
    )

    chosen = selection.resolve(executor, selection.WRITE, model="cli-model")
    manage = selection.resolve(executor, selection.MANAGE)

    assert chosen.reasoner == "endpoint"
    assert chosen.model == "cli-model"
    assert manage.model == "manage-model"


def test_an_unconfigured_reasoner_fails_closed():
    configured = dataclasses.replace(
        Config.default().executor, reasoner="surprise", model="m"
    )

    with pytest.raises(ReasonerUnavailableError, match="unsupported reasoner"):
        distiller.distiller(configured)


def test_unsupported_tool_modes_are_refused():
    executor = Config.default().executor
    executor.model = "m"
    executor.manage = OperationExecutorConfig(tool_mode="native")
    with pytest.raises(ReasonerUnavailableError):
        selection.resolve(executor, selection.MANAGE)


def test_write_accepts_auto_and_text_tool_modes():
    executor = Config.default().executor
    executor.model = "m"
    executor.write = OperationExecutorConfig(tool_mode=TOOL_MODE_AUTO)
    assert selection.resolve(executor, selection.WRITE).tool_mode == TOOL_MODE_AUTO
    executor.write = OperationExecutorConfig(tool_mode=TOOL_MODE_TEXT)
    assert selection.resolve(executor, selection.WRITE).tool_mode == TOOL_MODE_TEXT


def test_endpoint_write_text_mode_routes_through_the_line_protocol():
    executor = Config.default().executor
    executor.model = "m"
    executor.write = OperationExecutorConfig(reasoner="endpoint", tool_mode=TOOL_MODE_TEXT)

    reasoner = distiller.distiller(selection.resolve(executor, selection.WRITE))
    assert isinstance(reasoner, EndpointTextReasoner)


def test_an_unsupported_operation_is_refused():
    with pytest.raises(ReasonerUnavailableError):
        selection.resolve(Config.default().executor, "nonsense")


def test_a_default_executor_without_a_model_is_refused_loudly():
    with pytest.raises(ReasonerUnavailableError, match="no model configured"):
        distiller.distiller(Config.default().executor)
