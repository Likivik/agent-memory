"""Five-state standing machine: every state behaves like it claims."""

from __future__ import annotations

from mnemobun.core.config import Config
from mnemobun.core.docket import Docket
from mnemobun.core.recall import Recall
from mnemobun.core.record import (
    STANDING_ACCEPTED,
    STANDING_CONTESTED,
    STANDING_PROPOSED,
    STANDING_RETRACTED,
    STANDING_SUPERSEDED,
)
from mnemobun.core.standing import set_standing
from mnemobun.core.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "store", config=Config.default(), writer="standing-test")
    store.init()
    return store


def _claim(store, slug: str, name: str):
    return store.record(
        type="claim",
        fields={"project": "aurora"},
        abstract=f"{slug} service deploys note",
        body=f"{slug} note about service deploys.",
    )


def test_a_successor_starts_proposed_and_can_be_accepted_through_the_docket(tmp_path):
    store = _store(tmp_path)
    old = store.record(
        type="claim",
        fields={"project": "aurora"},
        abstract="aurora deploys Friday 22:00 UTC",
        body="Aurora deploys Friday at 22:00 UTC.",
    )
    new = store.record(
        type="claim",
        fields={"project": "aurora"},
        abstract="aurora deploys Saturday 09:00 UTC",
        body="Aurora now deploys Saturday at 09:00 UTC.",
        supersedes=old.name,
    )
    assert new.standing == STANDING_PROPOSED  # a new claim needs a ruling

    proposals = [item for item in Docket(store).proposals() if new.name in item.targets]
    assert proposals, "the successor must reach the docket for a ruling"
    Docket(store).decide(proposals[0].id, accept=True)

    assert store.find(new.name).standing == STANDING_ACCEPTED
    assert store.find(old.name).standing == STANDING_SUPERSEDED


def test_the_standing_ladder_ranks_accepted_above_contested_above_withdrawn(tmp_path):
    store = _store(tmp_path)
    withdrawn = _claim(store, "alpha", "withdrawn")
    superseded = _claim(store, "november", "superseded")
    contested = _claim(store, "mike", "contested")
    accepted = _claim(store, "zulu", "accepted")
    set_standing(store, accepted.name, STANDING_ACCEPTED, cause="test")
    set_standing(store, contested.name, STANDING_CONTESTED, cause="test")
    set_standing(store, withdrawn.name, STANDING_RETRACTED, cause="test")
    set_standing(store, superseded.name, STANDING_SUPERSEDED, cause="test")

    hits = [hit.name for hit in Recall(store).recall("service deploys", log=False)]

    # the withdrawn and superseded names sort first alphabetically; only the
    # standing ladder may put them below
    assert hits.index(accepted.name) < hits.index(contested.name)
    assert hits.index(contested.name) < hits.index(withdrawn.name)
    assert hits.index(contested.name) < hits.index(superseded.name)
