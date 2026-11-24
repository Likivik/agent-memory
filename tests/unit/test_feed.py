"""Feeding: feature extraction and the trigger decision (decision-only)."""

import datetime as dt
import sqlite3

from mnemobun.adapters import feed
from mnemobun.adapters.import_source import Turn
from mnemobun.core.config import Config
from mnemobun.core.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    return store


def _state_db(tmp_path, turns):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,"
            " role TEXT, content TEXT, timestamp TEXT, active INT, compacted INT)"
        )
        for index, (session, role, content) in enumerate(turns):
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, 1, 0)",
                (index, session, role, content, str(1000.0 + index)),
            )
    return path


def test_features_flag_tool_noise_and_repetition(tmp_path):
    store = _store(tmp_path)
    turn = Turn("s", "please remember the deploy window", "noted", "2026-01-01T00:00:00+00:00")
    fresh = feed.features_for(turn, [], store)
    repeated = feed.features_for(
        turn, ["please remember the deploy window noted"], store
    )
    assert fresh.is_user_text
    assert fresh.repetition == 0.0
    assert repeated.repetition == 1.0
    tool_turn = Turn("s", "", "tool output only", "2026-01-01T00:00:00+00:00")
    assert not feed.features_for(tool_turn, [], store).is_user_text


def test_messages_for_pairs_user_and_assistant():
    backlog = [Turn("s", "hi", "hello", "2026-01-01T00:00:00+00:00")]
    messages = feed.messages_for(backlog)
    assert [(m.role) for m in messages] == ["user", "assistant"]


def test_decision_only_run_writes_nothing(tmp_path):
    store = _store(tmp_path)
    db = _state_db(
        tmp_path,
        [("s1", "user", "remember that project aurora deploys Friday at 22:00 UTC"),
         ("s1", "assistant", "understood")],
    )
    config = store.config.usage
    object.__setattr__(config, "quiet_seconds", 0.0)
    object.__setattr__(config, "signal_threshold", 1.0)
    report = feed.run(store, state_db=db, ask=None, now=dt.datetime.now(dt.UTC))
    assert report.fired
    assert report.reason.startswith("decision only")
    assert report.backlog_turns == 1
    assert store.records() == []


def test_plan_mode_carries_projection_and_never_calls(tmp_path):
    store = _store(tmp_path)
    db = _state_db(
        tmp_path,
        [("s1", "user", "remember that project aurora deploys Friday at 22:00 UTC"),
         ("s1", "assistant", "understood")],
    )
    config = store.config.usage
    object.__setattr__(config, "quiet_seconds", 0.0)
    object.__setattr__(config, "signal_threshold", 1.0)
    report = feed.run(store, state_db=db, ask=None, now=dt.datetime.now(dt.UTC))
    assert report.projection is not None
    assert report.projection["calls"] >= 1


def test_spend_refusal_returns_exact_reason_and_writes_nothing(tmp_path):
    store = _store(tmp_path)
    db = _state_db(
        tmp_path,
        [("s1", "user", "remember that project aurora deploys Friday at 22:00 UTC"),
         ("s1", "assistant", "understood")],
    )
    config = store.config.usage
    object.__setattr__(config, "quiet_seconds", 0.0)
    object.__setattr__(config, "signal_threshold", 1.0)
    store.config.budget.max_calls_per_run = 0.5  # projection needs >= 1 call
    store.config.save(store.root)

    def ask(prompt: str) -> str:  # must never be reached
        raise AssertionError("ask called despite spend refusal")

    report = feed.run(store, state_db=db, ask=ask, now=dt.datetime.now(dt.UTC))
    assert report.reason.startswith("spend refused: max_calls_per_run; projected")
    assert store.records() == []


def test_gate_holds_when_signal_is_low(tmp_path):
    store = _store(tmp_path)
    db = _state_db(tmp_path, [("s1", "user", "ok"), ("s1", "assistant", "ok")])
    report = feed.run(store, state_db=db, ask=None, now=dt.datetime.now(dt.UTC))
    assert not report.fired
    assert report.reason == "signal or quiet gate"
