"""The Hermes tool surface for pinning: how a rule becomes always-on."""

from __future__ import annotations

from mnemobun.core import pinned
from mnemobun.mcp import tools


def test_memory_pin_marks_the_claim(store):
    store.record(name="rule-one", abstract="never prune containers without approval", type="claim")

    reply = tools.dispatch(store, "memory_pin", {"name": "rule-one"})

    assert "pinned" in str(reply["result"])
    assert "never prune" in pinned.render(store)


def test_memory_unpin_clears_it(store):
    store.record(name="rule-one", abstract="never prune containers", type="claim")
    tools.dispatch(store, "memory_pin", {"name": "rule-one"})

    tools.dispatch(store, "memory_unpin", {"name": "rule-one"})

    assert pinned.render(store) == ""
    assert store.find("rule-one") is not None


def test_both_tools_are_advertised(store):
    names = {tool["name"] for tool in tools.catalogue()}

    assert {"memory_pin", "memory_unpin"} <= names
