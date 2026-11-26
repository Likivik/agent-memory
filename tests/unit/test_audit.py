"""P2 acceptance: the answer-audit — labels, abstention, caps, logging."""

from __future__ import annotations

from mnemobun.core import audit
from mnemobun.core.access_log import AccessLog
from mnemobun.core.audit import KIND_VERIFY
from mnemobun.core.store import Store


def _seed(store):
    store.record(
        abstract="The backup schedule runs weekly btrfs snapshots on /var",
        type="preference",
        body="Snapshots run every Sunday at 03:00.",
        name="backup-schedule",
    )


def test_no_memory_hits_is_unsupported(store):
    result = audit.verify(
        store, "The user's favourite colour is teal", "favourite colour", labeler=None
    )
    assert result["label"] == audit.LABEL_UNSUPPORTED
    assert result["reason"] == "no memory hits"


def test_labeler_verdict_is_returned_and_logged(store):
    _seed(store)
    result = audit.verify(
        store,
        "Backups run weekly btrfs snapshots on /var",
        "backup schedule",
        labeler=lambda prompt: "supported",
    )
    assert result["label"] == audit.LABEL_SUPPORTED
    assert "backup-schedule" in result["evidence"]

    with store._database.connect() as connection:
        rows = [
            row for row in AccessLog(connection).entries() if row["kind"] == KIND_VERIFY
        ]
    assert rows


def test_labeler_error_abstains(store):
    _seed(store)

    def broken(prompt):
        raise RuntimeError("labeler down")

    result = audit.verify(
        store, "Backups run weekly", "backup schedule", labeler=broken
    )
    assert result["label"] == audit.LABEL_ABSTAIN


def test_unparseable_reply_abstains(store):
    _seed(store)
    result = audit.verify(
        store, "Backups run weekly", "backup schedule",
        labeler=lambda prompt: "the answer seems fine, I think",
    )
    assert result["label"] == audit.LABEL_ABSTAIN


def test_session_cap_abstains(store, config, clock, tmp_path):
    config.standing.audit_max_per_session = 2
    store = Store(tmp_path / "capped", config=config, clock=clock, writer="test-agent")
    store.init()
    _seed(store)
    for _ in range(2):
        result = audit.verify(
            store, "Backups run weekly", "backup schedule",
            labeler=lambda prompt: "unsupported",
        )
        assert result["label"] == audit.LABEL_UNSUPPORTED
    result = audit.verify(
        store, "Backups run weekly", "backup schedule", labeler=None
    )
    assert result["label"] == audit.LABEL_ABSTAIN
    assert result["reason"] == "session audit budget spent"


def test_labeler_none_abstains_without_verdict(store):
    _seed(store)
    result = audit.verify(store, "Backups run weekly", "backup schedule", labeler=None)
    assert result["label"] == audit.LABEL_ABSTAIN
    assert result["reason"] == "no labeler bound"
    assert result["evidence"]  # evidence retrieval still works


def test_conflicting_label_from_excerpts(store):
    _seed(store)
    store.record(
        abstract="The backup schedule was discontinued in favour of nightly rsync",
        type="preference",
        body="Nightly rsync replaced the Sunday snapshots.",
        name="backup-schedule-v2",
        supersedes="backup-schedule",
    )
    result = audit.verify(
        store,
        "Backups run weekly btrfs snapshots",
        "backup schedule",
        labeler=lambda prompt: "conflicting",
    )
    assert result["label"] == audit.LABEL_CONFLICTING
