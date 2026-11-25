"""Route resolution states: resolved, unset, unavailable, vanished."""

from __future__ import annotations

import pytest
from mnemobun.core.route import resolve_route
from mnemobun.core.settings import apply_settings
from mnemobun.core.store import Store


@pytest.fixture()
def store(tmp_path):
    created = Store(root=tmp_path / "store")
    created.init()
    return Store(root=tmp_path / "store")


def _set(store, provider, model):
    apply_settings(store, {"provider": provider, "model": model}, actor="test")
    return Store(root=store.root)


def test_unset(store):
    assert resolve_route(store, lambda: [("nous", "m")]).state == "unset"


def test_resolved(store):
    store = _set(store, "nous", "anthropic/claude-fable-5.2")
    state = resolve_route(store, lambda: [("nous", "anthropic/claude-fable-5.2")])
    assert state.state == "resolved" and state.usable


def test_unavailable_when_catalogue_missing(store):
    store = _set(store, "nous", "m")
    assert resolve_route(store, None).state == "unavailable"


def test_vanished_pair(store):
    store = _set(store, "nous", "gone")
    state = resolve_route(store, lambda: [("nous", "other")])
    assert state.state == "vanished"
    assert "no longer offered" in state.detail
