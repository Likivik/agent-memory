"""Write-time importance: 1-10, frozen, unrated (0) is neutral."""

import pytest
from mnemobun.core.config import Config
from mnemobun.core.errors import ValidationError
from mnemobun.core.store import Store
from mnemobun.core.toolkit import OPERATION_SCHEMA


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), agent="t")
    store.init()
    return store


def test_importance_round_trips_and_defaults_unrated(tmp_path):
    store = _store(tmp_path)
    plain = store.record(abstract="a plain note", type="fact")
    assert plain.importance == 0.0
    rated = store.record(abstract="a rated note", type="fact", importance=7.0)
    assert rated.importance == 7.0
    assert store.find(rated.name).importance == 7.0


def test_importance_bounds(tmp_path):
    store = _store(tmp_path)
    for bad in (-1.0, 10.5):
        with pytest.raises(ValidationError):
            store.record(abstract="bad", type="fact", importance=bad)
    assert store.record(abstract="low", type="fact", importance=1.0).importance == 1.0
    assert store.record(abstract="high", type="fact", importance=10.0).importance == 10.0


def test_operation_schema_declares_importance():
    assert "importance" in OPERATION_SCHEMA["properties"]
