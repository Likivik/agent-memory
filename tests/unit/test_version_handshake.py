"""Plugin<->store version handshake: drift is a named error, never a crash."""

import json

import pytest
from mnemobun.core.config import Config
from mnemobun.core.errors import StoreVersionError
from mnemobun.core.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "s", config=Config.default(), writer="t")
    store.init()
    return store


def test_fresh_store_gets_a_handshake(tmp_path):
    store = _store(tmp_path)
    known = json.loads((store.root / ".state" / "handshake.json").read_text())
    assert known["schema_version"] >= 3
    assert known["writer_version"]


def test_newer_store_version_is_a_named_error(tmp_path):
    store = _store(tmp_path)
    path = store.root / ".state" / "handshake.json"
    path.write_text(json.dumps({"schema_version": 99, "writer_version": "9.9.9"}))
    with pytest.raises(StoreVersionError) as excinfo:
        Store(store.root, config=Config.load(store.root), writer="t").init()
    message = str(excinfo.value)
    assert "store version 99 written by plugin 9.9.9" in message
    assert "this plugin is" in message


def test_older_store_version_is_migrated_and_marked_current(tmp_path):
    store = _store(tmp_path)
    path = store.root / ".state" / "handshake.json"
    path.write_text(json.dumps({"schema_version": 1, "writer_version": "0.0.1"}))
    Store(store.root, config=Config.load(store.root), writer="t").init()
    known = json.loads(path.read_text())
    assert known["schema_version"] >= 3
    assert known["writer_version"] != "0.0.1"
