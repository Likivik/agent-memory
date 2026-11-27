"""P1: the pinned-rules block renders deterministically, capped and loud."""

from __future__ import annotations

import pytest
from mnemobun.core import pinned
from mnemobun.core.errors import ValidationError


def _claim(store, name: str, abstract: str, **extra):
    return store.record(name=name, abstract=abstract, type="claim", **extra)


def test_only_flagged_claims_are_rendered(store):
    _claim(store, "rule-one", "never prune containers without approval")
    pinned.set_pinned(store, "rule-one", pinned=True)
    store.record(name="a-fact", abstract="the gateway runs on 9119", type="fact")
    store.record(name="a-turn", abstract="user said hello", type="event")

    text = pinned.render(store)

    assert "never prune containers" in text
    assert "gateway runs" not in text
    assert "user said hello" not in text


def test_order_is_pin_order_then_name(store):
    for name in ("rule-b", "rule-a"):
        _claim(store, name, f"text of {name}")
        pinned.set_pinned(store, name, pinned=True)
    _claim(store, "rule-first", "text of rule-first")
    pinned.set_pinned(store, "rule-first", pinned=True, order=1)

    lines = pinned.render(store).splitlines()

    assert lines[0].startswith("- text of rule-first")
    assert [line.split(" (")[0] for line in lines[1:]] == ["- text of rule-a", "- text of rule-b"]


def test_same_store_renders_same_digest(store):
    _claim(store, "rule-one", "keep answers short")
    pinned.set_pinned(store, "rule-one", pinned=True)

    assert pinned.block(store).digest == pinned.block(store).digest


def test_over_budget_truncation_is_explicit(store):
    store.config.recall.pinned_max_bytes = 80
    for index in range(4):
        _claim(store, f"rule-{index}", f"a rule long enough to fill the block {index}")
        pinned.set_pinned(store, f"rule-{index}", pinned=True)

    result = pinned.block(store)

    assert result.omitted > 0
    assert "pinned rule(s) omitted" in result.text


def test_contested_pin_is_refused(store):
    from mnemobun.core.standing import set_standing

    _claim(store, "rule-one", "always use podman")
    set_standing(store, "rule-one", "contested", cause="test", force=True)
    pinned.set_pinned(store, "rule-one", pinned=True)

    assert pinned.render(store) == ""


def test_deleting_a_pinned_claim_does_not_kill_the_block(store):
    _claim(store, "rule-one", "always ask first")
    _claim(store, "rule-two", "never prune")
    for name in ("rule-one", "rule-two"):
        pinned.set_pinned(store, name, pinned=True)
    for path in store.layout.truth_files():
        if path.stem.startswith("rule-one"):
            path.unlink()

    text = pinned.render(store)

    assert "never prune" in text  # one deleted rule cannot blank the rest
    assert "always ask first" not in text


def test_empty_store_renders_empty_string(store):
    assert pinned.render(store) == ""


def test_unpin_removes_the_rule_and_its_roster_entry(store):
    _claim(store, "rule-one", "no pruning")
    pinned.set_pinned(store, "rule-one", pinned=True)
    pinned.set_pinned(store, "rule-one", pinned=False)

    assert pinned.render(store) == ""


def test_facts_cannot_be_pinned(store):
    store.record(name="a-fact", abstract="gateway on 9119", type="fact")

    with pytest.raises(ValidationError):
        pinned.set_pinned(store, "a-fact", pinned=True)
