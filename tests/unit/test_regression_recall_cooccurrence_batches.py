from mnemobun.core.access_log import KIND_RECALL, AccessEntry, AccessLog
from mnemobun.core.database import Database
from mnemobun.core.dream import Dream


def test_repeated_query_counts_independent_cooccurrence_events(store):
    left = store.record(type="decision", name="left-fixture", abstract="Left fixture")
    right = store.record(type="decision", name="right-fixture", abstract="Right fixture")
    store.config.manage.link_cooccurrence_min = 2
    with Database(store.layout).connect() as connection:
        AccessLog(connection).append(
            [
                AccessEntry(at, name, "same query", KIND_RECALL, "fixture")
                for at in ["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]
                for name in [left.name, right.name]
            ]
        )
    actions = Dream(store)._add_cooccurrence_links([left, right])
    assert len(actions) == 2
    assert right.name in store.find(left.name).links


def test_same_query_on_separate_events_does_not_invent_cooccurrence(store):
    left = store.record(type="decision", name="left-fixture", abstract="Left fixture")
    right = store.record(type="decision", name="right-fixture", abstract="Right fixture")
    store.config.manage.link_cooccurrence_min = 1
    with Database(store.layout).connect() as connection:
        AccessLog(connection).append(
            [
                AccessEntry(
                    "2026-01-01T00:00:00+00:00", left.name, "same query", KIND_RECALL, "fixture"
                ),
                AccessEntry(
                    "2026-01-02T00:00:00+00:00", right.name, "same query", KIND_RECALL, "fixture"
                ),
            ]
        )
    assert Dream(store)._add_cooccurrence_links([left, right]) == []
