"""Replay driver (P9.4): write a source's history into a store as if accumulated.

Decisions implemented (docs/plans/import-replay-path.md):
- D1/D2: historical stamps via ``record_many(..., import_stamps=True)``; ``updated``
  = source timestamp so existing recency decay operates on true history.
- D3/D5: imported records enter ``accepted`` with provenance ``import-batch:<id>``
  (standing_policy="proposed" available for replay-strict runs).
- D4: exactly ONE deterministic dream pass at the end; the reasoner never runs —
  proposals stay open and drain through the normal nightly docket.
- D6: synthetic access entries (agent="import") so the first decay pass counts from
  import time, not from the historical timestamps.
- Idempotency (hard requirement): record names derive from the source turn's
  identity (session + instant + content), never from run counters. Re-running a
  replay upserts nothing and duplicates nothing — already-written turns are
  skipped by name. An aborted run resumes from the batch watermark instead of
  starting over; ``force=True`` resets the watermark and reprocesses from turn 0
  (already-written turns are still skipped, so a forced run stays clean).
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
from collections.abc import Iterable
from typing import Protocol

from mnemobun.core.access_log import KIND_READ, AccessEntry
from mnemobun.core.store import Store
from mnemobun.core.watermark import Watermark

PROVENANCE_IMPORT = "import-batch"
DEFAULT_BATCH_RECORDS = 2000
DIGEST_LENGTH = 12
WATERMARK_PREFIX = "replay"


class ReplaySource(Protocol):
    def turns(self) -> Iterable[object]: ...  # objects with session_id/user/assistant/at


@dataclasses.dataclass
class ReplayReport:
    written: int
    rejected: list[str]
    batches: int
    dream_actions: int
    skipped: int = 0  # turns already present in the store (idempotent re-runs)


def _slug_session(session_id: str, *, max_len: int) -> str:
    slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in session_id.lower())
    return slug[:max_len]


def _source_key(source: object) -> str:
    """A stable identity for the source, so a rerun resumes the same watermark.

    A name alone is not an identity: a different database behind the same file
    name would resume another source's position. The key therefore includes a
    fingerprint of the file's first pages (stable under appends) — a different
    file gets its own watermark instead of a wrong resume. Files without a
    readable path fall back to the name alone.
    """
    path = str(getattr(source, "_path", "") or "")
    raw = str(path or getattr(source, "name", "") or "source")
    slug = _slug_session(pathlib.Path(raw).name or "source", max_len=40) or "source"
    fingerprint = ""
    if path:
        try:
            with open(path, "rb") as handle:
                head = handle.read(65536)
            fingerprint = hashlib.sha256(head).hexdigest()[:DIGEST_LENGTH]
        except OSError:
            fingerprint = ""
    return f"{slug}-{fingerprint}" if fingerprint else slug


def _turn_name(store: Store, session: str, at: str, user: str, assistant: str) -> str:
    """Deterministic per source turn: same turn -> same name, every run."""
    digest = hashlib.sha256(
        f"{session}\x00{at}\x00{user}\x00{assistant}".encode()
    ).hexdigest()[:DIGEST_LENGTH]
    slug = _slug_session(
        session or "anon",
        max_len=max(1, store.config.storage.slug_max_length - len("turn-") - 1 - DIGEST_LENGTH),
    )
    return f"turn-{slug}-{digest}"


def _existing_names(store: Store) -> set[str]:
    """Every record name already in the store, gathered in one scan."""
    return {path.stem for path in store.root.rglob("*.md")}


def replay(
    store: Store,
    source,
    *,
    standing_policy: str = "accepted",
    batch_id: str = "",
    batch_records: int = DEFAULT_BATCH_RECORDS,
    run_dream: bool = True,
    force: bool = False,
) -> ReplayReport:
    if standing_policy not in ("accepted", "proposed"):
        raise ValueError("standing_policy must be 'accepted' or 'proposed'")
    key = f"{WATERMARK_PREFIX}-{batch_id or _source_key(source)}"
    marker = f"{PROVENANCE_IMPORT}:{batch_id or _source_key(source)}"
    report = ReplayReport(written=0, rejected=[], batches=0, dream_actions=0)
    max_abstract = store.config.storage.abstract_max_chars

    watermark = Watermark(store.layout, store.clock)
    if force:
        watermark.reset(key)
    consumed = watermark.read(key).consumed  # turns already processed in earlier runs

    existing = _existing_names(store)
    specs: list[dict[str, object]] = []
    names: list[str] = []
    processed = consumed

    def flush() -> None:
        nonlocal specs, names, processed, consumed
        if specs:
            result = store.record_many(specs, assume_new=True, import_stamps=True)
            report.written += len(result.written)
            report.batches += 1
            for rejected in result.rejected:
                report.rejected.append(f"[{rejected.index}] {rejected.errors}")
            # D6: synthetic access entries so decay counts from import, not history.
            entries = [
                AccessEntry(
                    at=store.clock.timestamp(),
                    name=name,
                    query="",
                    kind=KIND_READ,
                    agent="import",
                )
                for name in names
            ]
            store.log_access(entries)
            existing.update(names)
            specs, names = [], []
        if processed > consumed:
            watermark.advance(key, processed)
            consumed = processed

    turns = source.turns()
    for index, turn in enumerate(turns):
        if index < consumed:  # resumed runs skip what earlier runs already committed
            report.skipped += 1
            continue
        processed += 1
        user = str(getattr(turn, "user", "")).strip()
        assistant = str(getattr(turn, "assistant", "")).strip()
        if not user:  # a turn is a user+assistant pair (D8); assistant-only rows skipped
            continue
        at = str(getattr(turn, "at", "")).strip()
        session = str(getattr(turn, "session_id", "")).strip()
        name = _turn_name(store, session, at, user, assistant)
        if name in existing:  # already written (this run or an earlier one)
            report.skipped += 1
            continue
        abstract_source = " ".join(user.split()) or " ".join(assistant.split())
        names.append(name)
        specs.append(
            {
                "type": "event",
                "name": name,
                "abstract": abstract_source[:max_abstract],
                "body": f"USER: {user}\nASSISTANT: {assistant}",
                "author": "import",
                "standing": standing_policy,
                "provenance": [marker],
                "created": at,
                "updated": at,
            }
        )
        if len(specs) >= batch_records:
            flush()
    flush()

    if run_dream and report.written:
        from mnemobun.core.dream import Dream

        dream = Dream(store).sleep(reasoner=None, dream_id="import")
        report.dream_actions = len(getattr(dream, "actions", []) or [])
    return report
