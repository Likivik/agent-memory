"""P6: pinning is a ruled decision, and a full block refuses rather than truncates."""

from __future__ import annotations

import pytest
from mnemobun.core import pinned
from mnemobun.core.docket import Docket
from mnemobun.core.errors import ValidationError


def _claim(store, name: str, abstract: str):
    return store.record(name=name, abstract=abstract, type="claim")


def test_pin_sets_the_flag_and_the_roster(store):
    _claim(store, "rule-one", "never prune containers without approval")

    assert Docket(store).pin("rule-one") == "pinned rule-one"

    assert "never prune containers" in pinned.render(store)


def test_unpin_keeps_the_claim_but_stops_delivery(store):
    _claim(store, "rule-one", "report in STE")
    Docket(store).pin("rule-one")

    Docket(store).unpin("rule-one")

    assert pinned.render(store) == ""
    assert store.find("rule-one") is not None


def test_pin_is_refused_when_the_block_is_full(store):
    store.config.recall.pinned_max_bytes = 120
    _claim(store, "rule-one", "a rule long enough to fill the whole pinned block")
    _claim(store, "rule-two", "another rule that cannot fit beside the first one")

    Docket(store).pin("rule-one")
    with pytest.raises(ValidationError, match="pinned block full"):
        Docket(store).pin("rule-two")

    assert "rule-two" not in pinned.render(store)


def test_pin_refuses_a_non_claim(store):
    store.record(name="a-fact", abstract="gateway on 9119", type="fact")

    with pytest.raises(ValidationError):
        Docket(store).pin("a-fact")


def test_pin_and_unpin_have_sleep_caps(store):
    """Without a cap entry the review loop withholds the proposal silently."""
    caps = Docket(store)._caps()

    assert caps["pin"] > 0
    assert caps["unpin"] > 0
