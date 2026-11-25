"""P7: pin candidates come from citation counts, not from a model."""

from __future__ import annotations

from mnemobun.core.docket import Docket
from mnemobun.core.dream import PROPOSAL_PIN, PROPOSAL_UNPIN
from mnemobun.core.standing import set_standing


def _claim(store, name: str, abstract: str):
    return store.record(name=name, abstract=abstract, type="claim")


def _kinds(store, hits):
    return [(p.kind, p.targets[0]) for p in Docket(store).proposals(hits=hits)]


def test_claim_cited_above_threshold_becomes_a_pin_proposal(store):
    _claim(store, "rule-one", "approved tooling is podman")

    assert (PROPOSAL_PIN, "rule-one") in _kinds(store, {"rule-one": 5})


def test_claim_below_threshold_proposes_nothing(store):
    _claim(store, "rule-one", "approved tooling is podman")

    assert (PROPOSAL_PIN, "rule-one") not in _kinds(store, {"rule-one": 1})


def test_already_pinned_claim_is_not_proposed_again(store):
    _claim(store, "rule-one", "approved tooling is podman")
    Docket(store).pin("rule-one")

    assert (PROPOSAL_PIN, "rule-one") not in _kinds(store, {"rule-one": 9})


def test_candidates_are_deterministic(store):
    for name in ("rule-b", "rule-a"):
        _claim(store, name, f"text {name}")

    assert _kinds(store, {"rule-a": 4, "rule-b": 4}) == _kinds(store, {"rule-a": 4, "rule-b": 4})


def test_contested_pin_raises_an_unpin_proposal(store):
    _claim(store, "rule-one", "approved tooling is podman")
    Docket(store).pin("rule-one")
    set_standing(store, "rule-one", "contested", cause="test", force=True)

    assert (PROPOSAL_UNPIN, "rule-one") in _kinds(store, {})
