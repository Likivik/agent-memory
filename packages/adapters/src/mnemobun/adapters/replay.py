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
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterable
from typing import Protocol

from mnemobun.core.access_log import KIND_READ, AccessEntry
from mnemobun.core.store import Store

PROVENANCE_IMPORT = "import-batch"
DEFAULT_BATCH_RECORDS = 2000


class ReplaySource(Protocol):
    def turns(self) -> Iterable[object]: ...  # objects with session_id/user/assistant/at


@dataclasses.dataclass
class ReplayReport:
    written: int
    rejected: list[str]
    batches: int
    dream_actions: int


def _slug_session(session_id: str, *, max_len: int) -> str:
    slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in session_id.lower())
    return slug[:max_len]


def replay(
    store: Store,
    source,
    *,
    standing_policy: str = "accepted",
    batch_id: str = "",
    batch_records: int = DEFAULT_BATCH_RECORDS,
    run_dream: bool = True,
) -> ReplayReport:
    if standing_policy not in ("accepted", "proposed"):
        raise ValueError("standing_policy must be 'accepted' or 'proposed'")
    marker = f"{PROVENANCE_IMPORT}:{batch_id or store.clock.stamp().lower()}"
    report = ReplayReport(written=0, rejected=[], batches=0, dream_actions=0)
    max_abstract = store.config.storage.abstract_max_chars

    turns = source.turns()
    while True:
        chunk = list(itertools.islice(turns, batch_records))
        if not chunk:
            break
        specs: list[dict[str, object]] = []
        names: list[str] = []
        for index, turn in enumerate(chunk):
            user = str(getattr(turn, "user", "")).strip()
            assistant = str(getattr(turn, "assistant", "")).strip()
            if not user:  # a turn is a user+assistant pair (D8); assistant-only rows skipped
                continue
            at = str(getattr(turn, "at", "")).strip()
            session = _slug_session(
                str(getattr(turn, "session_id", "")).strip() or "anon",
                max_len=max(1, store.config.storage.slug_max_length - len("turn--000000")),
            )
            name = f"turn-{session}-{report.written + index:06d}"
            names.append(name)
            abstract_source = " ".join(user.split()) or " ".join(assistant.split())
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
        if not specs:
            continue
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

    if run_dream and report.written:
        from mnemobun.core.dream import Dream

        dream = Dream(store).sleep(reasoner=None, dream_id="import")
        report.dream_actions = len(getattr(dream, "actions", []) or [])
    return report
