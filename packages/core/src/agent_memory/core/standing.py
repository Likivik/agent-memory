"""The standing machine: five states, deterministic transitions, DRed-lite propagation.

Semantics per the research note (Trilium: *Agent Memory Architecture* §10.3 — the cortex TMS)
and design-doc decisions 1–5:

- States: proposed | accepted | contested | retracted | superseded. The file frontmatter field
  `standing` is the source of truth; the SQLite `standing_history` table and the
  `state/standing-journal.jsonl` side file record every transition (the index is a deletable
  cache, so the journal lives outside it).
- Transitions are computed here, never by a reasoner. The Manage menu may only *propose*
  accept/contest items (see `manage.py`); users may confirm or reject.
- Support: a claim is supported while every plain link target is active (not retracted or
  superseded). Contest never propagates — a claim citing a contested claim keeps its own
  standing (arXiv:2611.05753, the cortex paper's best single idea).
- Propagation is DRed-lite (lemmalog review): losing support retracts dependents with cause
  `support_lost`; restoring support re-proposes them — unless the journal shows a
  `user_reject`, which is permanent.
- Conflicts are recorded as `links` entries prefixed with `CONFLICT_PREFIX` and are created
  only by explicit agent tool arguments (design decision 3) — never auto-detected.
"""

from __future__ import annotations

import json
import pathlib

from .database import Database
from .errors import FieldError, NotFoundError, ValidationError
from .record import (
    CONFLICT_PREFIX,
    STANDING_ACCEPTED,
    STANDING_CONTESTED,
    STANDING_PROPOSED,
    STANDING_RETRACTED,
    STANDING_STATES,
    STANDING_SUPERSEDED,
    MemoryRecord,
)
from .store import Store

CAUSE_SUPPORT_LOST = "support_lost"
CAUSE_SUPPORT_RESTORED = "support_restored"
CAUSE_USER_REJECT = "user_reject"
CAUSE_USER_CONFIRM = "user_confirm"
CAUSE_CONFLICT_ADDED = "conflict_added"
CAUSE_CONFLICT_CLEARED = "conflict_cleared"
CAUSE_SUPERSEDED = "superseded"
JOURNAL_FILENAME = "standing-journal.jsonl"
LIVE_STATES = (STANDING_PROPOSED, STANDING_ACCEPTED, STANDING_CONTESTED)


def antecedents(record: MemoryRecord) -> list[str]:
    """Plain link targets — the claims/events this claim rests on."""
    return [link for link in record.links if not link.startswith(CONFLICT_PREFIX)]


def conflicts_of(record: MemoryRecord) -> list[str]:
    """Peer claims this claim contradicts (explicit, agent-declared only)."""
    return [
        link[len(CONFLICT_PREFIX):]
        for link in record.links
        if link.startswith(CONFLICT_PREFIX)
    ]


def _journal_path(store: Store) -> pathlib.Path:
    return store.layout.state_dir / JOURNAL_FILENAME


def _append_journal(store: Store, claim: str, from_standing: str | None, to_standing: str,
                    cause: str, at: str) -> None:
    """Side journal: the durable audit trail outside the rebuildable index cache."""
    path = _journal_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"claim": claim, "from": from_standing, "to": to_standing,
             "cause": cause, "at": at}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record_history(store: Store, connection, claim: str, from_standing: str | None,
                   to_standing: str, cause: str, at: str) -> None:
    """Write the transition into the index cache's history table and the side journal."""
    connection.execute(
        "INSERT INTO standing_history(claim, from_standing, to_standing, cause, at) "
        "VALUES(?, ?, ?, ?, ?)",
        (claim, from_standing, to_standing, cause, at),
    )
    _append_journal(store, claim, from_standing, to_standing, cause, at)


def _record(store: Store, name: str) -> MemoryRecord:
    record = store.find(name)
    if record is None or record.path is None:
        raise NotFoundError(f"no memory named {name}")
    return record


def _write_standing(store: Store, record: MemoryRecord, to_standing: str, cause: str,
                    at: str, connection) -> MemoryRecord:
    from_standing = record.standing
    record.standing = to_standing
    record.updated = at
    written = store.write(record)
    record_history(store, connection, written.name, from_standing, to_standing, cause, at)
    return written


def set_standing(store: Store, name: str, to_standing: str, cause: str, at: str | None = None,
                 *, force: bool = False) -> MemoryRecord:
    """Set one claim's standing directly (user confirm/reject, supersede side-effect).

    `force` bypasses the transition table for callers that already validated the move
    (the Manage apply path and the supersede side-effect inside store.supersede).
    """
    if to_standing not in STANDING_STATES:
        raise ValidationError([FieldError("standing", f"unknown standing: {to_standing}")])
    moment = at or store.clock.now().isoformat()
    record = _record(store, name)
    if record.standing == to_standing:
        return record
    if not force and to_standing == STANDING_ACCEPTED and record.standing == STANDING_PROPOSED:
        cause = cause or CAUSE_USER_CONFIRM
    if not force and not _transition_allowed(record.standing, to_standing):
        raise ValidationError([FieldError(
            "standing", f"illegal transition for {name}: {record.standing} -> {to_standing}"
        )])
    with Database(store.layout).connect() as connection:
        return _write_standing(store, record, to_standing, cause, moment, connection)


def _transition_allowed(from_standing: str, to_standing: str) -> bool:
    if from_standing == to_standing:
        return True
    if to_standing == STANDING_RETRACTED:
        return from_standing in LIVE_STATES
    if from_standing == STANDING_RETRACTED:
        return to_standing == STANDING_PROPOSED  # user-reject guard lives in the caller
    if to_standing == STANDING_SUPERSEDED:
        return True  # the supersede flow owns its preconditions
    if to_standing == STANDING_CONTESTED:
        return from_standing in (STANDING_PROPOSED, STANDING_ACCEPTED)
    if to_standing == STANDING_ACCEPTED:
        return from_standing in (STANDING_PROPOSED, STANDING_CONTESTED)
    return False


def add_conflict(store: Store, name: str, peer: str, at: str | None = None) -> MemoryRecord:
    """Record an explicit contradiction between two live claims (decision 3: agent-declared)."""
    moment = at or store.clock.now().isoformat()
    record = _record(store, name)
    _record(store, peer)  # fail fast when the peer does not exist
    link = CONFLICT_PREFIX + peer
    if link in record.links:
        return record
    record.links.append(link)
    record.updated = moment
    written = store.write(record)
    if written.standing in LIVE_STATES:
        with Database(store.layout).connect() as connection:
            written = _write_standing(store, _record(store, written.name), STANDING_CONTESTED,
                                      CAUSE_CONFLICT_ADDED, moment, connection)
    return written


def clear_conflict(store: Store, name: str, peer: str, at: str | None = None) -> MemoryRecord:
    """Remove a declared contradiction (an edit, not an override — cortex §3)."""
    moment = at or store.clock.now().isoformat()
    record = _record(store, name)
    link = CONFLICT_PREFIX + peer
    if link not in record.links:
        return record
    record.links = [entry for entry in record.links if entry != link]
    record.updated = moment
    written = store.write(record)
    with Database(store.layout).connect() as connection:
        _write_standing(store, _record(store, written.name), STANDING_ACCEPTED,
                        CAUSE_CONFLICT_CLEARED, moment, connection)
    return written


def propagate(store: Store, at: str | None = None) -> list[dict[str, str]]:
    """Recompute support over the whole claim graph (DRed-lite fixpoint).

    Small scale by design (thousands of claims): a full recompute per pass is simpler and
    easier to differential-test than incremental deltas, and lemmalog's lesson — retraction
    must be symmetric with insertion — is preserved by re-evaluating restores in the same pass.
    Returns the transitions applied.
    """
    moment = at or store.clock.now().isoformat()
    claims = [
        record for record in store.records(include_invalid=True) if record.type == "claim"
    ]
    by_name = {record.name: record for record in claims}
    ever_rejected = _ever_rejected(store)

    def supported(record: MemoryRecord) -> bool:
        for target in antecedents(record):
            peer = by_name.get(target)
            if peer is None:
                continue  # links to non-claim memories (events, facts) don't gate support
            if peer.standing in (STANDING_RETRACTED, STANDING_SUPERSEDED):
                return False
        return True

    applied: list[dict[str, str]] = []
    with Database(store.layout).connect() as connection:
        # Pass 1: withdraw support (fixpoint — a retracted antecedent can cascade).
        changed = True
        while changed:
            changed = False
            for record in claims:
                if record.standing in (STANDING_ACCEPTED, STANDING_PROPOSED, STANDING_CONTESTED) \
                        and not supported(record):
                    _write_standing(store, record, STANDING_RETRACTED,
                                    CAUSE_SUPPORT_LOST, moment, connection)
                    record.standing = STANDING_RETRACTED
                    applied.append({"claim": record.name, "to": STANDING_RETRACTED,
                                    "cause": CAUSE_SUPPORT_LOST})
                    changed = True
        # Pass 2: restore support (DRed symmetry) — never for user-rejected claims.
        for record in claims:
            if record.standing == STANDING_RETRACTED \
                    and record.name not in ever_rejected \
                    and _last_cause(store, record.name) == CAUSE_SUPPORT_LOST \
                    and supported(record):
                _write_standing(store, record, STANDING_PROPOSED,
                                CAUSE_SUPPORT_RESTORED, moment, connection)
                record.standing = STANDING_PROPOSED
                applied.append({"claim": record.name, "to": STANDING_PROPOSED,
                                "cause": CAUSE_SUPPORT_RESTORED})
    return applied


def _ever_rejected(store: Store) -> set[str]:
    path = _journal_path(store)
    rejected: set[str] = set()
    if not path.exists():
        return rejected
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("cause") == CAUSE_USER_REJECT:
            rejected.add(str(entry.get("claim")))
    return rejected


def _last_cause(store: Store, name: str) -> str | None:
    path = _journal_path(store)
    last: str | None = None
    if not path.exists():
        return last
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("claim") == name:
            last = str(entry.get("cause"))
    return last


def timeline(store: Store, name: str) -> dict[str, object]:
    """Proof tree for a claim: its antecedents, their standings, and the conflict set.

    The audit primitive (lemmalog's `why()`): every derived belief answers 'what rests
    on what, and where did each leg come from'.
    """
    record = _record(store, name)
    legs: list[dict[str, object]] = []
    for target in antecedents(record):
        peer = store.find(target)
        legs.append({
            "name": target,
            "type": peer.type if peer else None,
            "standing": peer.standing if peer else None,
            "path": str(peer.path) if peer and peer.path else None,
        })
    history: list[dict[str, str]] = []
    with Database(store.layout).connect() as connection:
        rows = connection.execute(
            "SELECT from_standing, to_standing, cause, at FROM standing_history "
            "WHERE claim = ? ORDER BY at, rowid",
            (name,),
        ).fetchall()
        for row in rows:
            history.append({
                "from": row["from_standing"], "to": row["to_standing"],
                "cause": row["cause"], "at": row["at"],
            })
    return {
        "name": name,
        "standing": record.standing,
        "antecedents": legs,
        "conflicts": conflicts_of(record),
        "provenance": list(record.provenance),
        "history": history,
    }
