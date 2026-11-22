"""Authenticated Codex coverage for the complete native Dream review path."""

import json
import os
import pathlib

import pytest
from mnemobun.cli.main import main
from mnemobun.core.config import OperationExecutorConfig
from mnemobun.core.ledger import LEDGER_FILENAME
from mnemobun.core.manage_toolkit import TOOL_READ, TOOL_SUBMIT
from mnemobun.core.store import Store

LIVE = os.environ.get("AGENT_MEMORY_LIVE_CODEX") == "1"
MODEL = os.environ.get("AGENT_MEMORY_LIVE_CODEX_MODEL", "gpt-5.6-sol")

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="set AGENT_MEMORY_LIVE_CODEX=1 for authenticated Codex Dream coverage",
)


def test_live_codex_reviews_evidence_and_submits_verdicts(tmp_path, capsys):
    store = Store(tmp_path / "store", agent="live-manage-seed")
    store.init()
    store.config.manage.git_commit = False
    store.config.executor.manage = OperationExecutorConfig(
        reasoner="host",
        host="codex",
        host_model=MODEL,
        tool_mode="native",
        timeout_seconds=180.0,
    )
    store.config.save(store.root)
    store.record(
        type="fact",
        name="queue-window-old",
        abstract="Queue drain window closes before worker lease",
        body="The original note says the drain window is shorter than the lease.",
    )
    store.record(
        type="fact",
        name="queue-window-current",
        abstract="Queue drain window closes before worker lease on staging",
        body=(
            "On staging the queue drain window is 20 seconds and the worker lease is 30 seconds. "
            "Raise drain_timeout above the lease TTL."
        ),
    )

    assert main(["--json", "--store", str(store.root), "sleep"]) == 0
    payload = json.loads(capsys.readouterr().out)
    review = payload["review"]
    names = [item["name"] for item in review["tool_trace"]]

    assert review["mode"] == "native"
    assert review["complete"] is True
    assert TOOL_READ in names
    assert names[-1] == TOOL_SUBMIT
    assert review["evidence_reads"]
    assert review["input_tokens"] is not None
    assert review["output_tokens"] is not None
    assert payload["decisions"]
    assert pathlib.Path(payload["path"]).is_file()
    assert (store.layout.dream_reports / LEDGER_FILENAME).is_file()
