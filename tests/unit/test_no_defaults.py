"""R7: an unset harness, reasoner or channel is refused, never filled in.

Each refuser says which value was missing and where. A default here would run a write or a
delivery against a harness nobody chose, which is the failure this rule exists to prevent.
"""

from __future__ import annotations

import io
import json

import pytest
from mnemobun.adapters import channels, hook_entry
from mnemobun.core.config import ExecutorConfig
from mnemobun.executor import selection


def test_a_hook_without_a_harness_is_refused_by_its_command_line(store, monkeypatch):
    stdin = io.StringIO(json.dumps({"hook_event_name": "SessionStart", "store": str(store.root)}))
    monkeypatch.setattr("sys.stdin", stdin)

    with pytest.raises(SystemExit) as refusal:
        hook_entry.main(())

    assert refusal.value.code != 0


def test_an_empty_reasoner_runs_deterministic_only_and_says_so():
    config = ExecutorConfig(reasoner="")

    with pytest.raises(Exception) as refusal:
        selection.resolve(config, selection.WRITE)

    assert "unsupported reasoner ''" in str(refusal.value)
    assert selection.WRITE in str(refusal.value)


def test_delivering_to_an_unknown_harness_names_it():
    with pytest.raises(KeyError) as refusal:
        channels.for_harness("not-a-harness")

    assert "no channel registered for harness: not-a-harness" in str(refusal.value)
