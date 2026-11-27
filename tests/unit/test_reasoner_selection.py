"""Operation policy resolution: host only, merge rules, loud refusals."""

from __future__ import annotations

import dataclasses

import pytest
from mnemobun.core.config import ExecutorConfig, OperationExecutorConfig
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.executor import selection


def test_write_merges_the_operation_policy_over_the_executor_policy():
    executor = ExecutorConfig(reasoner="codex", timeout_seconds=30.0)
    resolved = selection.resolve(executor, selection.WRITE)
    assert resolved.reasoner == "codex"
    assert resolved.timeout_seconds == 30.0


def test_operation_policy_can_override_the_reasoner():
    executor = dataclasses.replace(
        ExecutorConfig(),
        write=OperationExecutorConfig(reasoner="codex", timeout_seconds=5.0),
    )
    resolved = selection.resolve(executor, selection.WRITE)
    assert resolved.reasoner == "codex"
    assert resolved.timeout_seconds == 5.0


def test_unknown_reasoners_are_refused():
    with pytest.raises(ReasonerUnavailableError, match="unsupported reasoner"):
        selection.resolve(ExecutorConfig(reasoner="bogus-dialect"), selection.WRITE)


def test_an_unknown_reasoner_override_is_refused():
    with pytest.raises(ReasonerUnavailableError, match="unsupported reasoner"):
        selection.resolve(ExecutorConfig(), selection.WRITE, reasoner="nope")


def test_an_unsupported_operation_is_refused():
    with pytest.raises(ReasonerUnavailableError, match="unsupported memory operation"):
        selection.resolve(ExecutorConfig(), "delete")


def test_explicit_cli_fields_override_the_selected_operation_policy():
    executor = ExecutorConfig(reasoner="codex", model="")
    resolved = selection.resolve(executor, selection.MANAGE, model="m1")
    assert resolved.model == "m1"
