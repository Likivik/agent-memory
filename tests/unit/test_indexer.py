"""M2 — the projection: incremental, rebuildable, and never authoritative."""

from mnemobun.core.database import Database
from mnemobun.core.recall import Recall
from mnemobun.core.search_index import SearchIndex


def _names(hits):
    return {hit.name for hit in hits}


def test_touching_one_file_reindexes_only_that_file(seeded):
    seeded.sync_index()
    seeded.record(
        abstract="Queue drain window is now 90 seconds",
        type="fact",
        name="drain-window",
    )
    report = seeded.sync_index()
    assert report.reindexed == ()

    target = seeded.find("file-truth-invariant")
    target.body = target.body + "\nAppended a line.\n"
    target.path.write_text(target.to_text(), encoding="utf-8")
    report = seeded.sync_index()
    assert [path.split("/")[-1] for path in report.reindexed] == ["file-truth-invariant.md"]


def test_rebuild_after_deleting_the_index_returns_the_same_recall_set(seeded):
    seeded.record(
        abstract="Second deploy note about the drain window",
        type="experience",
        name="drain-window-note",
    )
    seeded.correct("file-truth-invariant", body="Rewritten body about file truth and indexes.")
    queries = ["deploy drain queue", "file truth index rebuild", "concise answers"]
    before = {query: _names(Recall(seeded).recall(query)) for query in queries}

    seeded.layout.index_db.unlink()
    seeded.rebuild_index()

    after = {query: _names(Recall(seeded).recall(query)) for query in queries}
    assert after == before


def test_rebuild_is_idempotent(seeded):
    first = seeded.rebuild_index()
    second = seeded.rebuild_index()
    assert set(first.reindexed) == set(second.reindexed)


def test_a_legacy_dangling_link_is_reported_by_rebuild(store):
    written = store.record(
        abstract="Points at a memory that does not exist yet",
        type="fact",
        name="forward-reference",
    )
    written.links = ["not-written-yet"]
    written.path.write_text(written.to_text())
    report = store.rebuild_index()
    assert ("forward-reference", "not-written-yet") in report.dangling_links


def test_removing_a_file_drops_it_from_the_projection(seeded):
    seeded.find("file-truth-invariant").path.unlink()
    report = seeded.sync_index()
    assert any("file-truth-invariant" in path for path in report.removed)
    with Database(seeded.layout).connect() as connection:
        assert SearchIndex(connection).row("file-truth-invariant") is None



