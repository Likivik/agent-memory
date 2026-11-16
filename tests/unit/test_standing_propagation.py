"""P1 acceptance: DRed-lite edge cases — illegal transitions, supersede side-effects."""

from __future__ import annotations

import pytest
from agent_memory.core import standing
from agent_memory.core.errors import ValidationError
from agent_memory.core.record import (
    STANDING_ACCEPTED,
    STANDING_CONTESTED,
    STANDING_PROPOSED,
    STANDING_RETRACTED,
    STANDING_SUPERSEDED,
)


def _claim(store, name: str, abstract: str, links: list[str] | None = None):
    return store.record(
        abstract=abstract,
        type="claim",
        body=abstract,
        name=name,
        links=links or [],
    )


def test_illegal_transition_is_rejected(store):
    claim = _claim(store, "fresh-claim", "A fresh claim nobody ruled on")
    standing.set_standing(store, claim.name, STANDING_RETRACTED, cause="user_reject")
    with pytest.raises(ValidationError):
        standing.set_standing(store, claim.name, STANDING_CONTESTED, cause="user_confirm")


def test_retracted_to_accepted_must_pass_through_proposed(store):
    claim = _claim(store, "fresh-claim", "A fresh claim nobody ruled on")
    standing.set_standing(store, claim.name, STANDING_RETRACTED, cause="user_reject")
    with pytest.raises(ValidationError):
        standing.set_standing(store, claim.name, STANDING_ACCEPTED, cause="user_confirm")
    proposed = standing.set_standing(
        store, claim.name, STANDING_PROPOSED, cause="user_confirm"
    )
    assert proposed.standing == STANDING_PROPOSED


def test_unknown_standing_is_rejected(store):
    claim = _claim(store, "fresh-claim", "A fresh claim nobody ruled on")
    with pytest.raises(ValidationError):
        standing.set_standing(store, claim.name, "vibes", cause="user_confirm")


def test_superseded_antecedent_retracts_dependents(store):
    base = _claim(store, "origin-is-nixos", "This host runs NixOS")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    dependent = _claim(
        store, "depends-on-origin", "Depends on the origin claim", links=[base.name]
    )
    standing.set_standing(store, dependent.name, STANDING_ACCEPTED, cause="user_confirm")

    successor = _claim(store, "origin-is-nixos-v2", "This host runs NixOS (verified)")
    store.supersede(base.name, successor.name)
    assert store.find(base.name).standing == STANDING_SUPERSEDED

    standing.propagate(store)
    assert store.find(dependent.name).standing == STANDING_RETRACTED
