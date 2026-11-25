"""The pinned-rules block: a deterministic, byte-capped floor of standing rules.

Rendered once from the store, delivered by a host channel into the system prompt — the only
place compaction cannot drop it (arXiv 2606.22528: +0 decay in a preserved system message
versus +45 as a memory entry). Facts never enter this block; they belong to recall.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

from .config import (
    PIN_ORDER_DEFAULT,
    PIN_ORDER_FIELD,
    PINNED_DATE_CHARS,
    PINNED_FIELD,
    PINNED_REFUSED_STANDING,
    PINNED_ROSTER_FILENAME,
    PINNED_ROSTER_INDENT,
    PINNED_TYPES,
)
from .errors import FieldError, ValidationError
from .record import MemoryRecord
from .store import Store

TRUNCATION_MARKER = "- ({count} pinned rule(s) omitted: block full)"


@dataclasses.dataclass(frozen=True)
class PinnedRule:
    name: str
    line: str
    order: int


@dataclasses.dataclass(frozen=True)
class PinnedBlock:
    rules: tuple[PinnedRule, ...]
    omitted: int
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def _flagged(record: MemoryRecord) -> bool:
    return str(record.fields.get(PINNED_FIELD, "")).strip().lower() in {"true", "yes", "1"}


def _order(record: MemoryRecord) -> int:
    raw = str(record.fields.get(PIN_ORDER_FIELD, "")).strip()
    try:
        return int(raw) if raw else PIN_ORDER_DEFAULT
    except ValueError as error:
        raise ValidationError(
            [FieldError(PIN_ORDER_FIELD, f"not an integer: {raw}")]
        ) from error


def _line(record: MemoryRecord) -> str:
    """Rule text plus its provenance: the record name and the day it last changed."""
    stamp = (record.updated or record.created)[:PINNED_DATE_CHARS]
    return f"- {record.abstract} ({record.name}, {stamp})"


def _roster_path(store: Store):
    return store.layout.state_dir / PINNED_ROSTER_FILENAME


def _roster(store: Store) -> dict[str, str]:
    path = _roster_path(store)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValidationError([FieldError(PINNED_FIELD, f"roster unreadable: {path}")]) from error
    return {str(k): str(v) for k, v in dict(raw).items()}


def _eligible(record: MemoryRecord) -> bool:
    if not _flagged(record):
        return False
    if record.type not in PINNED_TYPES:
        return False
    return record.standing not in PINNED_REFUSED_STANDING


def is_pinned(record: MemoryRecord) -> bool:
    return _flagged(record)


def block(store: Store) -> PinnedBlock:
    """Every pinned rule that may be rendered, in a stable order, capped by bytes.

    A name in the roster whose record no longer exists is an error: a rule cannot be lost
    silently.
    """
    roster = _roster(store)
    records = {record.name: record for record in store.records()}
    missing = sorted(name for name in roster if name not in records)
    if missing:
        raise ValidationError(
            [FieldError(PINNED_FIELD, f"pinned record missing: {', '.join(missing)}")]
        )
    rules = sorted(
        (PinnedRule(name=r.name, line=_line(r), order=_order(r))
         for r in records.values() if _eligible(r)),
        key=lambda rule: (rule.order, rule.name),
    )
    budget = store.config.recall.pinned_max_bytes
    kept: list[PinnedRule] = []
    used = 0
    for rule in rules:
        size = len(rule.line.encode("utf-8")) + 1
        if used + size > budget:
            break
        kept.append(rule)
        used += size
    omitted = len(rules) - len(kept)
    lines = [rule.line for rule in kept]
    if omitted:
        lines.append(TRUNCATION_MARKER.format(count=omitted))
    return PinnedBlock(rules=tuple(kept), omitted=omitted, text="\n".join(lines))


def render(store: Store) -> str:
    return block(store).text


def set_pinned(store: Store, name: str, *, pinned: bool, order: int | None = None,
               ) -> MemoryRecord:
    """Mark or unmark a claim as a standing rule. Deterministic; no model involved."""
    records = {record.name: record for record in store.records()}
    record = records.get(name)
    if record is None:
        raise ValidationError([FieldError("name", f"no such record: {name}")])
    if pinned and record.type not in PINNED_TYPES:
        raise ValidationError([FieldError("type", f"only {sorted(PINNED_TYPES)} can be pinned")])
    updated = dict(record.fields)
    if pinned:
        updated[PINNED_FIELD] = "true"
        if order is not None:
            updated[PIN_ORDER_FIELD] = str(order)
    else:
        updated.pop(PINNED_FIELD, None)
        updated.pop(PIN_ORDER_FIELD, None)
    record.fields = updated
    written = store.write(record)
    _record_roster(store, name, order, pinned=pinned)
    return written


def _record_roster(store: Store, name: str, order: int | None, *, pinned: bool) -> None:
    roster = _roster(store)
    if pinned:
        roster[name] = str(order if order is not None else PIN_ORDER_DEFAULT)
    else:
        roster.pop(name, None)
    path = _roster_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(roster, indent=PINNED_ROSTER_INDENT, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")
