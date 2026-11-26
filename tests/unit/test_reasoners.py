"""Executors: text out, text back, and silence whenever the outside world misbehaves."""

import dataclasses
import json
import pathlib
import subprocess

import pytest
from mnemobun.core.errors import ReasonerUnavailableError
from mnemobun.executor.drivers import DriverResult
from mnemobun.executor.reasoners import DriverReasoner


class FakeHost:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.result


def _reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def test_a_host_reasoner_passes_the_prompt_through_and_returns_the_answer():
    host = FakeHost(DriverResult(text="verdict line", ok=True, seconds=0.1))
    assert DriverReasoner(host=host)("review this") == "verdict line"
    assert host.calls[0][0] == "review this"


def test_a_host_reasoner_asks_for_no_tools():
    host = FakeHost(DriverResult(text="ok", ok=True, seconds=0.1))
    DriverReasoner(host=host)("review this")
    assert host.calls[0][1]["tools_enabled"] is False


def test_a_failed_host_is_reported():
    host = FakeHost(DriverResult(text="usage: claude ...", ok=False, seconds=0.1, error="boom"))
    with pytest.raises(ReasonerUnavailableError, match="host reasoner failed.*boom"):
        DriverReasoner(host=host)("review this")


def test_an_empty_host_reply_is_reported():
    host = FakeHost(DriverResult(text="", ok=True, seconds=0.1))
    with pytest.raises(ReasonerUnavailableError, match="empty response"):
        DriverReasoner(host=host)("review this")


def test_a_driver_is_named_by_harness_and_runs_that_harness_s_binary():
    from mnemobun.executor.drivers import BINARIES, HARNESS_CODEX
    from mnemobun.executor.reasoners import DriverReasoner

    reasoner = DriverReasoner.for_host(HARNESS_CODEX)
    assert reasoner.host.spec.binary == BINARIES[HARNESS_CODEX][0]
    assert reasoner.host.spec.model == BINARIES[HARNESS_CODEX][1]


def test_an_unknown_driver_fails_closed_instead_of_using_another_harness():
    with pytest.raises(ReasonerUnavailableError, match="unsupported host reasoner"):
        DriverReasoner.for_host("not-a-host")


def test_codex_jsonl_usage_is_retained_for_native_review_metrics(tmp_path, monkeypatch):
    from mnemobun.executor import drivers

    def run(command, **kwargs):
        pathlib.Path(command[command.index("--output-last-message") + 1]).write_text("done")
        stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "cached_input_tokens": 80,
                    "output_tokens": 12,
                },
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(drivers.driver.subprocess, "run", run)
    host = drivers.Driver(drivers.DriverSpec(name="codex", binary="codex", attempts=1))
    result = host.run("review", workdir=tmp_path)

    assert result.ok and result.usage is not None
    assert result.usage.turns == 1
    assert result.usage.input_tokens == 120
    assert result.usage.cached_input_tokens == 80
    assert result.usage.output_tokens == 12






def test_codex_jsonl_trace_separates_startup_model_mcp_and_shutdown():
    from mnemobun.executor.drivers import _CodexTrace

    trace = _CodexTrace(started=10.0)
    trace.observe(json.dumps({"type": "thread.started"}), 11.0)
    trace.observe(
        json.dumps(
            {
                "type": "item.started",
                "item": {"id": "call-1", "type": "mcp_tool_call"},
            }
        ),
        14.0,
    )
    trace.observe(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "call-1", "type": "mcp_tool_call"},
            }
        ),
        14.5,
    )
    trace.observe(json.dumps({"type": "turn.completed"}), 19.0)

    phases = trace.phases(finished=20.0)

    assert phases is not None
    assert phases.startup_seconds == 1.0
    assert phases.model_wait_seconds == 7.5
    assert phases.mcp_seconds == 0.5
    assert phases.shutdown_seconds == 1.0
    assert sum(dataclasses.astuple(phases)) == 10.0


def test_a_host_reasoner_marks_its_session_as_the_executor_so_hooks_stand_down():
    from mnemobun.core.config import EXECUTOR_ENV_VAR

    host = FakeHost(DriverResult(text="ok", ok=True, seconds=0.1))
    DriverReasoner(host=host)("review this")
    assert host.calls[0][1]["environment"][EXECUTOR_ENV_VAR]



