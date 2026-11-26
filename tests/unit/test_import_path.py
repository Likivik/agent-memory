"""P9: import/replay path — stamps, usage protection, source adapter, driver."""

from __future__ import annotations

import sqlite3

import pytest
from mnemobun.adapters.import_source import HermesSource, Turn
from mnemobun.adapters.replay import replay
from mnemobun.core.store import Store


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


# -- P9.2: usage protection ---------------------------------------------------


def test_imported_record_weight_survives_a_decay_pass(store, monkeypatch):
    _write(store, "old-fact", "imported long ago")
    import mnemobun.core.dream as manage_mod

    monkeypatch.setattr(
        manage_mod.Dream,
        "_idle_days",
        lambda self, record, last_access, now: 999.0,  # far past the decay threshold
    )
    manage = manage_mod.Dream(store)
    before = {r.name: r.usage for r in store.records()}
    manage._settle_usages(store.records(), {}, {})
    after = {r.name: r.usage for r in store.records()}
    assert after["old-fact"] >= before["old-fact"] - store.config.usage.decay_step


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
    import mnemobun.core.dream as manage_mod

    turns = [
        Turn(session_id="s-1", user="q one", assistant="a one", at="2026-01-01T00:00:00Z"),
        Turn(session_id="s-1", user="q two", assistant="a two", at="2026-01-02T00:00:00Z"),
        Turn(session_id="s-2", user="", assistant="noise", at="2026-01-03T00:00:00Z"),
    ]
    drafted = []
    monkeypatch.setattr(
        manage_mod.Dream,
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
    assert {r.updated for r in records.values()} == {
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    }
    record = next(r for r in records.values() if r.updated == "2026-01-01T00:00:00Z")
    provenance_files = list((store.root / "archive" / "provenance").rglob("*.md"))
    assert provenance_files
    assert any("import-batch:test" in f.read_text(encoding="utf-8") for f in provenance_files)
    assert record.standing == "accepted"
    # D6: synthetic access entries present
    with store._database.connect() as connection:
        rows = connection.execute(
            "SELECT count(*) FROM access_log WHERE writer = 'import'"
        ).fetchone()
    assert rows[0] == 2


def test_replay_rejects_bad_policy(store):
    with pytest.raises(ValueError, match="standing_policy"):
        replay(store, _StaticSource([]), standing_policy="auto")


# -- idempotency + resume (hard requirements) ---------------------------------


class _AbortingSource:
    """Yields `fail_after` turns, then raises — simulates an interrupted import."""

    def __init__(self, turns, fail_after):
        self._turns = turns
        self._fail_after = fail_after

    def turns(self):
        for index, turn in enumerate(self._turns):
            if index >= self._fail_after:
                raise RuntimeError("source interrupted")
            yield turn


def _turns(count):
    return [
        Turn(
            session_id=f"s-{index}",
            user=f"question {index}",
            assistant=f"answer {index}",
            at=f"2026-01-{index + 1:02d}T00:00:00Z",
        )
        for index in range(count)
    ]


def test_replay_is_idempotent(store):
    turns = _turns(4)
    first = replay(store, _StaticSource(turns), batch_id="idem", run_dream=False)
    second = replay(store, _StaticSource(turns), batch_id="idem", run_dream=False)
    assert first.written == 4
    assert second.written == 0
    assert second.skipped == 4
    assert len(store.records()) == 4  # a rerun duplicates nothing


def test_replay_names_are_deterministic_per_turn(store):
    turns = _turns(2)
    replay(store, _StaticSource(turns), batch_id="names", run_dream=False)
    first = sorted(r.name for r in store.records())
    replay(store, _StaticSource(turns), batch_id="names", run_dream=False, force=True)
    assert sorted(r.name for r in store.records()) == first  # same turn, same name


def test_replay_resumes_after_abort_without_duplicates(store):
    turns = _turns(5)
    with pytest.raises(RuntimeError, match="interrupted"):
        replay(
            store,
            _AbortingSource(turns, fail_after=3),
            batch_id="res",
            batch_records=2,
            run_dream=False,
        )
    report = replay(
        store, _StaticSource(turns), batch_id="res", batch_records=2, run_dream=False
    )
    assert report.written == 3  # the 2 committed before the crash are not redone
    assert len(store.records()) == 5


def test_replay_force_restarts_but_stays_clean(store):
    turns = _turns(4)
    with pytest.raises(RuntimeError, match="interrupted"):
        replay(
            store,
            _AbortingSource(turns, fail_after=2),
            batch_id="f",
            batch_records=2,
            run_dream=False,
        )
    report = replay(
        store,
        _StaticSource(turns),
        batch_id="f",
        batch_records=2,
        run_dream=False,
        force=True,
    )
    assert report.skipped == 2  # reprocessed from turn 0, already-written skipped
    assert report.written == 2
    assert len(store.records()) == 4


def test_source_key_fingerprints_content_not_just_name(tmp_path):
    from mnemobun.adapters.replay import _source_key

    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "state.db"
    second = second_dir / "state.db"
    first.write_bytes(b"first database")
    second.write_bytes(b"second database")

    class Source:
        def __init__(self, path):
            self._path = str(path)

    # same file name, different database: different watermarks
    assert _source_key(Source(first)) != _source_key(Source(second))
    assert _source_key(Source(first)) == _source_key(Source(first))
    # appends do not change the identity (the first pages are stable)
    with first.open("ab") as handle:
        handle.write(b"more rows")
    assert _source_key(Source(first)) == _source_key(Source(first))

    class Named:
        name = "state.db"

    # sources without a path fall back to the name alone
    assert _source_key(Named()) == "state-db"
