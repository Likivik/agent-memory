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


def _cite(store, name: str, queries: list[str]) -> None:
    from mnemobun.core.access_log import KIND_RECALL, AccessEntry, AccessLog

    entries = [AccessEntry(at="2026-01-15T09:00:00+00:00", name=name, query=q, kind=KIND_RECALL,
                           writer="test") for q in queries]
    with store._database.connect() as connection:  # noqa: SLF001 - the log has no public door
        AccessLog(connection).append(entries)


def test_one_query_repeated_does_not_propose_a_pin(store):
    _claim(store, "rule-one", "approved tooling is podman")
    store.config.manage.pin_min_queries = 3
    _cite(store, "rule-one", ["same question"] * 9)

    assert not [p for p in Docket(store).proposals() if p.kind == PROPOSAL_PIN]


def test_many_distinct_queries_do_propose_a_pin(store):
    _claim(store, "rule-one", "approved tooling is podman")
    store.config.manage.pin_min_queries = 3
    _cite(store, "rule-one", ["q1", "q2", "q3", "q4"])

    assert [p for p in Docket(store).proposals() if p.kind == PROPOSAL_PIN]


def test_full_block_proposes_unpinning_the_least_cited_rule(store):
    for name in ("rule-often", "rule-rarely"):
        _claim(store, name, f"{name} text long enough to matter")
        Docket(store).pin(name)
    store.config.recall.pinned_max_bytes = 90  # shrink after pinning: the block now overflows
    with_block = [p for p in Docket(store).proposals(hits={"rule-often": 9, "rule-rarely": 1})
                  if p.kind == PROPOSAL_UNPIN]

    assert with_block and with_block[0].targets[0] == "rule-rarely"
