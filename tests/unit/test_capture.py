"""Turn capture: verbatim body, stable identity, replay refused."""

from __future__ import annotations

import pytest
from mnemobun.core.slug import is_valid_slug
from mnemobun.core.store import Store
from mnemobun.executor.capture import TurnCaptureService


@pytest.fixture()
def store(tmp_path):
    root = tmp_path / "store"
    created = Store(root=root)
    created.init()
    return Store(root=root)


@pytest.mark.parametrize(
    "session_id",
    ["20261101_173738_8ba95851", "agent:x:local:dm:local-" + "ab" * 32, ""],
)
def test_turn_lands_with_valid_name(store, session_id):
    result = TurnCaptureService(store).capture("привет", "ответ", session_id=session_id)
    assert result["written"], result
    assert is_valid_slug(result["written"])
    assert store.find(result["written"]) is not None


def test_body_is_verbatim(store):
    user, assistant = "first line", "second line — with detail"
    result = TurnCaptureService(store).capture(user, assistant, session_id="s1")
    record = store.find(result["written"])
    assert record is not None
    assert f"USER: {user}" in record.body
    assert f"ASSISTANT: {assistant}" in record.body
    assert record.abstract == user


def test_replay_is_refused_not_renamed(store):
    service = TurnCaptureService(store)
    service.capture("same", "turn", session_id="s1")
    again = service.capture("same", "turn", session_id="s1")
    assert again["written"] == ""
    assert again["skipped"] == "dedupe_refused"


def test_empty_turn_is_skipped(store):
    assert TurnCaptureService(store).capture("  ", "", session_id="s1")["skipped"] == "empty"
