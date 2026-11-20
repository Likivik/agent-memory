"""P1 acceptance: the standing machine's menu path, journal, and proof tree."""

from __future__ import annotations

import json

from agent_memory.core import standing
from agent_memory.core.recall import Recall
from agent_memory.core.record import (
    STANDING_ACCEPTED,
    STANDING_CONTESTED,
    STANDING_PROPOSED,
    STANDING_RETRACTED,
)
from agent_memory.core.standing import CAUSE_SUPPORT_LOST, CAUSE_SUPPORT_RESTORED


def _claim(store, name: str, abstract: str, links: list[str] | None = None):
    return store.record(
        abstract=abstract,
        type="claim",
        body=abstract,
        name=name,
        links=links or [],
    )


def test_new_claim_starts_proposed_and_menu_accepts(store):
    claim = _claim(store, "use-btrfs-snapshots", "Weekly btrfs snapshots protect /var")
    assert claim.standing == STANDING_PROPOSED

    accepted = standing.set_standing(
        store, claim.name, STANDING_ACCEPTED, cause="user_confirm"
    )
    assert accepted.standing == STANDING_ACCEPTED

    with store._database.connect() as connection:
        rows = connection.execute(
            "SELECT to_standing, cause FROM standing_history WHERE claim = ?",
            (claim.name,),
        ).fetchall()
    assert [(row["to_standing"], row["cause"]) for row in rows] == [
        (STANDING_ACCEPTED, "user_confirm")
    ]


def test_restore_after_retract_propagates_back(store):
    base = _claim(store, "origin-is-nixos", "This host runs NixOS")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    dependent = _claim(
        store,
        "rollback-is-safe",
        "Rollbacks are safe because the host runs NixOS",
        links=[base.name],
    )
    standing.set_standing(store, dependent.name, STANDING_ACCEPTED, cause="user_confirm")

    # Retract the antecedent: the dependent loses support (DRed forward pass).
    standing.set_standing(store, base.name, STANDING_RETRACTED, cause="user_reject")
    applied = standing.propagate(store)
    assert {
        "claim": dependent.name,
        "to": STANDING_RETRACTED,
        "cause": CAUSE_SUPPORT_LOST,
    } in applied

    # Restore the antecedent: the dependent comes back as `proposed`, not silently accepted.
    standing.set_standing(store, base.name, STANDING_PROPOSED, cause="user_confirm")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    applied = standing.propagate(store)
    assert {
        "claim": dependent.name,
        "to": STANDING_PROPOSED,
        "cause": CAUSE_SUPPORT_RESTORED,
    } in applied
    assert store.find(dependent.name).standing == STANDING_PROPOSED


def test_user_reject_is_permanent(store):
    base = _claim(store, "origin-is-nixos", "This host runs NixOS")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    dependent = _claim(
        store, "depends-on-origin", "Depends on the origin claim", links=[base.name]
    )
    standing.set_standing(store, dependent.name, STANDING_ACCEPTED, cause="user_confirm")
    standing.set_standing(store, base.name, STANDING_RETRACTED, cause="user_reject")
    standing.propagate(store)

    journal = store.layout.state_dir / standing.JOURNAL_FILENAME
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"claim": dependent.name, "cause": "user_reject"}) + "\n")

    standing.set_standing(store, base.name, STANDING_PROPOSED, cause="user_confirm")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    applied = standing.propagate(store)
    assert applied == []
    assert store.find(dependent.name).standing == STANDING_RETRACTED


def test_conflict_contests_but_does_not_propagate(store):
    base = _claim(store, "origin-is-nixos", "This host runs NixOS")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    dependent = _claim(
        store, "cites-base", "Cites the origin claim", links=[base.name]
    )
    standing.set_standing(store, dependent.name, STANDING_ACCEPTED, cause="user_confirm")
    peer = _claim(store, "origin-is-debian", "This host runs Debian")
    standing.set_standing(store, peer.name, STANDING_ACCEPTED, cause="user_confirm")

    contested = standing.add_conflict(store, dependent.name, peer.name)
    assert contested.standing == STANDING_CONTESTED
    # Contest never propagates: the antecedent and the peer keep their own standing.
    assert store.find(base.name).standing == STANDING_ACCEPTED
    assert store.find(peer.name).standing == STANDING_ACCEPTED


def test_contested_ranks_below_accepted_in_recall(store):
    first = _claim(store, "alpha-claim", "Deploys ship every Tuesday")
    second = _claim(store, "beta-claim", "Deploys ship every Tuesday afternoon")
    standing.set_standing(store, second.name, STANDING_CONTESTED, cause="conflict_added")

    hits = Recall(store).recall("deploys ship")
    by_name = {hit.name: hit for hit in hits}
    assert by_name[first.name].score > by_name[second.name].score
    assert by_name[second.name].standing == STANDING_CONTESTED


def test_forget_session_retracts_events_claims_and_dependents(store):
    from agent_memory.core.record import STANDING_RETRACTED

    # session s1: two turns + a claim derived from them + an unrelated claim
    event = store.record(
        abstract="s1 said backups are weekly", type="event",
        body="turn body", name="turn-s1-20260115t090000000000",
        provenance=["session:s1"],
    )
    derived = store.record(
        abstract="Backups are weekly", type="claim", body="x",
        name="backups-weekly", links=[event.name],
    )
    standing.set_standing(store, derived.name, STANDING_ACCEPTED, cause="user_confirm")
    bystander = store.record(
        abstract="Unrelated session fact", type="claim", body="x", name="bystander"
    )
    standing.set_standing(store, bystander.name, STANDING_ACCEPTED, cause="user_confirm")

    result = standing.forget_session(store, "s1")
    assert event.name in result["forgotten"]
    assert store.find(event.name).standing == STANDING_RETRACTED
    assert store.find(event.name).invalid_at is not None
    # the derived claim loses its support through propagation
    assert store.find(derived.name).standing == STANDING_RETRACTED
    # the bystander is untouched
    assert store.find(bystander.name).standing == STANDING_ACCEPTED


def test_forget_session_is_permanent_across_restores(store):
    from agent_memory.core.record import STANDING_RETRACTED

    event = store.record(
        abstract="s2 turned the flag on", type="event", body="x",
        name="turn-s2-20260115t090100000000", provenance=["session:s2"],
    )
    claim = store.record(
        abstract="The flag is on", type="claim", body="x",
        name="flag-on", links=[event.name],
    )
    standing.set_standing(store, claim.name, STANDING_ACCEPTED, cause="user_confirm")

    standing.forget_session(store, "s2")
    assert store.find(claim.name).standing == STANDING_RETRACTED

    # Even a manual un-invalidate + support restore must not resurrect it.
    revived = store.find(claim.name)
    revived.invalid_at = None
    store.write(revived)
    applied = standing.propagate(store)
    restores = [a for a in applied if a["claim"] == claim.name]
    assert restores == []
    assert store.find(claim.name).standing == STANDING_RETRACTED


def test_timeline_shows_proof_tree(store):
    base = _claim(store, "origin-is-nixos", "This host runs NixOS")
    standing.set_standing(store, base.name, STANDING_ACCEPTED, cause="user_confirm")
    dependent = _claim(
        store, "cites-base", "Cites the origin claim", links=[base.name]
    )

    standing.set_standing(store, dependent.name, STANDING_ACCEPTED, cause="user_confirm")
    tree = standing.timeline(store, dependent.name)
    assert tree["name"] == dependent.name
    assert tree["antecedents"][0]["name"] == base.name
    assert tree["antecedents"][0]["standing"] == STANDING_ACCEPTED
    assert any(row["to"] == STANDING_ACCEPTED for row in tree["history"])
