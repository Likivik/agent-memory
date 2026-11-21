"""P9: import/replay path — stamps, weight protection, source adapter, driver."""

from __future__ import annotations

import sqlite3

import pytest
from agent_memory.adapters.import_source import HermesSource, Turn
from agent_memory.adapters.replay import replay
from agent_memory.core.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(root=tmp_path / "store")


def _write(store, name, abstract):
    store.record(name=name, abstract=abstract, type="fact")


# -- P9.1: import stamps -----------------------------------------------------


def test_import_stamps_are_accepted_and_preserved(store):
    result = store.record_many(
        [
            {
                "type": "event",
                "name": "hist-001",
                "abstract": "a past turn",
                "created": "2026-01-15T10:00:00Z",
                "updated": "2026-01-15T10:00:00Z",
            }
        ],
        assume_new=True,
        import_stamps=True,
    )
    assert len(result.written) == 1
    record = result.written[0]
    assert record.created == "2026-01-15T10:00:00Z"
    assert record.updated == "2026-01-15T10:00:00Z"
    assert record.valid_from == "2026-01-15T10:00:00Z"


def test_future_import_stamp_is_rejected(store):
    result = store.record_many(
        [
            {
                "type": "event",
                "name": "future-001",
                "abstract": "from tomorrow",
                "updated": "2099-01-01T00:00:00+00:00",
            }
        ],
        assume_new=True,
        import_stamps=True,
    )
    assert result.written == []
    assert any(e.field == "updated" for e in result.rejected[0].errors)


def test_live_path_still_rejects_import_stamps(store):
    result = store.record_many(
        [
            {
                "type": "event",
                "name": "live-001",
                "abstract": "now",
                "updated": "2026-01-15T10:00:00Z",
            }
        ],
        assume_new=True,
    )
    assert result.written == []
    assert any("unknown field: updated" in str(e.errors) for e in result.rejected)


def test_invalid_import_stamp_is_rejected(store):
    result = store.record_many(
        [
            {
                "type": "event",
                "name": "bad-001",
                "abstract": "not a stamp",
                "updated": "not-a-date",
            }
        ],
        assume_new=True,
        import_stamps=True,
    )
    assert result.written == []


# -- P9.2: weight protection ---------------------------------------------------


def test_imported_record_weight_survives_a_decay_pass(store, monkeypatch):
    _write(store, "old-fact", "imported long ago")
    import agent_memory.core.manage as manage_mod

    monkeypatch.setattr(
        manage_mod.Manage,
        "_idle_days",
        lambda self, record, last_access, now: 999.0,  # far past the decay threshold
    )
    manage = manage_mod.Manage(store)
    before = {r.name: r.weight for r in store.records()}
    manage._settle_weights(store.records(), {}, {})
    after = {r.name: r.weight for r in store.records()}
    assert after["old-fact"] >= before["old-fact"] - store.config.weight.decay_step


# -- P9.3: HermesSource ---------------------------------------------------------


def _make_state_db(path, rows):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
        "content TEXT, timestamp TEXT, active INTEGER, compacted INTEGER)"
    )
    connection.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp, active, compacted) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def test_source_schema_probe_fails_loud(tmp_path):
    db = tmp_path / "state.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="schema drift"):
        HermesSource(db)


def test_source_pairs_turns_in_chronological_order(tmp_path):
    db = tmp_path / "state.db"
    _make_state_db(
        db,
        [
            ("s-b", "user", "second session q", "100.0", 1, 0),
            ("s-a", "user", "first q", "50.0", 1, 0),
            ("s-a", "tool", '{"ignored": true}', "51.0", 1, 0),
            ("s-a", "assistant", "first a", "52.0", 1, 0),
            ("s-a", "assistant", "compacted away", "53.0", 1, 1),
            ("s-a", "user", "", "54.0", 1, 0),  # empty: skipped
            ("s-b", "assistant", "second a", "101.0", 1, 0),
        ],
    )
    turns = list(HermesSource(db).turns())
    assert [(t.session_id, t.user, t.assistant) for t in turns] == [
        ("s-a", "first q", "first a"),
        ("s-b", "second session q", "second a"),
    ]
    assert turns[0].at.startswith("1970-01-01T00:01:") or "+" in turns[0].at


# -- P9.4: replay driver -------------------------------------------------------


class _StaticSource:
    def __init__(self, turns):
        self._turns = turns

    def turns(self):
        return iter(self._turns)


def test_replay_writes_history_with_provenance_and_dreams_deterministically(store, monkeypatch):
    import agent_memory.core.manage as manage_mod

    turns = [
        Turn(session_id="s-1", user="q one", assistant="a one", at="2026-01-01T00:00:00Z"),
        Turn(session_id="s-1", user="q two", assistant="a two", at="2026-01-02T00:00:00Z"),
        Turn(session_id="s-2", user="", assistant="noise", at="2026-01-03T00:00:00Z"),
    ]
    drafted = []
    monkeypatch.setattr(
        manage_mod.Manage,
        "sleep",
        lambda self, reasoner=None, *, dream_id="": drafted.append(dream_id)
        or manage_mod.DreamReport(at="2026-01-01T00:00:00Z", actions=(), proposals=(), inspected=0),
    )
    report = replay(store, _StaticSource(turns), batch_id="test", batch_records=1)
    assert report.written == 2  # empty user+assistant pair skipped
    assert report.batches == 2
    assert drafted == ["import"]  # exactly one deterministic pass, reasoner never runs
    records = {r.name: r for r in store.records()}
    assert any(name.startswith("turn-s-1-") for name in records)
    record = next(r for name, r in records.items() if name.startswith("turn-s-1-"))
    assert record.updated == "2026-01-01T00:00:00Z"
    provenance_files = list((store.root / "archive" / "provenance").rglob("*.md"))
    assert provenance_files
    assert any("import-batch:test" in f.read_text(encoding="utf-8") for f in provenance_files)
    assert record.standing == "accepted"
    # D6: synthetic access entries present
    with store._database.connect() as connection:
        rows = connection.execute(
            "SELECT count(*) FROM access_log WHERE agent = 'import'"
        ).fetchone()
    assert rows[0] == 2


def test_replay_rejects_bad_policy(store):
    with pytest.raises(ValueError, match="standing_policy"):
        replay(store, _StaticSource([]), standing_policy="auto")
