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


def test_an_empty_reasoner_means_deterministic_only():
    chosen = selection.resolve(ExecutorConfig(reasoner=""), selection.WRITE)

    assert chosen.reasoner == ""


def test_an_unknown_reasoner_is_refused_by_name():
    config = ExecutorConfig(reasoner="not-a-driver")

    with pytest.raises(Exception) as refusal:
        selection.resolve(config, selection.MANAGE)

    assert "unsupported reasoner 'not-a-driver'" in str(refusal.value)
    assert selection.MANAGE in str(refusal.value)


def test_delivering_to_an_unknown_harness_names_it():
    with pytest.raises(KeyError) as refusal:
        channels.for_harness("not-a-harness")

    assert "no channel registered for harness: not-a-harness" in str(refusal.value)


def test_an_index_this_version_cannot_read_is_dropped_not_upgraded(store):
    import sqlite3

    layout = store.layout
    layout.index_db.unlink(missing_ok=True)
    old = sqlite3.connect(layout.index_db)
    old.execute("CREATE TABLE records (id TEXT PRIMARY KEY, status TEXT)")
    old.execute("INSERT INTO records VALUES ('stale', 'accepted')")
    old.execute("PRAGMA user_version = 3")
    old.commit()
    old.close()

    from mnemobun.core.database import Database

    with Database(layout).connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(records)")}
        rows = connection.execute("SELECT count(*) FROM records").fetchone()[0]

    assert "status" not in columns
    assert "writer" in columns
    assert rows == 0
