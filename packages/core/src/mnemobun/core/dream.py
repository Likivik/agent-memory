"""The dream: sleep-time consolidation run.

A Dream is one night of the store's life: the deterministic half (date
normalisation, weight settling, co-occurrence links, duplicate and cluster
merges) runs unconditionally; the judged half is drafted as a docket
(`mnemobun.core.docket.Docket`) and handed to the reasoner, which can only
choose from what was drafted. Every dream leaves a report, and a git commit
when the store lives in a repository.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import re
from collections.abc import Iterable

from . import reasoning, timestamp
from .access_log import KIND_READ, AccessLog
from .clock import Clock
from .ledger import Decision
from .record import DATE_FIELDS, MemoryRecord
from .schema import SOURCE_MENU, source_of
from .store import Store


def _review_dict(outcome: reasoning.ReviewOutcome | None) -> dict[str, object] | None:
    if outcome is None:
        return None
    return {
        "mode": outcome.mode,
        "submitted": outcome.submitted,
        "complete": outcome.complete,
        "rounds": outcome.rounds,
        "tool_calls": outcome.tool_calls,
        "duration_seconds": outcome.duration_seconds,
        "startup_seconds": outcome.startup_seconds,
        "model_wait_seconds": outcome.model_wait_seconds,
        "mcp_seconds": outcome.mcp_seconds,
        "shutdown_seconds": outcome.shutdown_seconds,
        "apply_seconds": outcome.apply_seconds,
        "model_requests": outcome.model_requests,
        "agent_turns": outcome.agent_turns,
        "input_tokens": outcome.input_tokens,
        "cached_input_tokens": outcome.cached_input_tokens,
        "output_tokens": outcome.output_tokens,
        "evidence_reads": [list(item) for item in outcome.evidence_reads],
        "provenance_reads": [list(item) for item in outcome.provenance_reads],
        "tool_trace": [
            {"name": name, "is_error": is_error} for name, is_error in outcome.tool_trace
        ],
        "error": outcome.error,
    }

def _metric(value: int | None) -> str:
    return str(value) if value is not None else "unavailable"

def _seconds(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "unavailable"

def _report_values(label: str, values: Iterable[str]) -> str:
    rendered = ", ".join(values)
    return f"- {label}:" + (f" {rendered}" if rendered else "")

def _tokens(text: str) -> set[str]:
    return {word for word in _WORDS.findall(text.lower()) if word not in _STOPWORDS}

def _contradiction_shape(first: MemoryRecord, second: MemoryRecord) -> bool:
    """Same subject, opposite negation polarity: the cheapest reliable contradiction
    shape. Deterministic drafting only — the sleep reasoner still rules on the pair."""
    tokens_first = _tokens(first.abstract)
    tokens_second = _tokens(second.abstract)
    if not tokens_first or not tokens_second:
        return False
    overlap = len(tokens_first & tokens_second) / max(len(tokens_first | tokens_second), 1)
    if overlap < CONFLICT_OVERLAP_MIN:
        return False
    return (bool(tokens_first & NEGATION_CUES) != bool(tokens_second & NEGATION_CUES))

def _similarity(left: MemoryRecord, right: MemoryRecord) -> float:
    first = _tokens(left.abstract)
    second = _tokens(right.abstract)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)

def _duplicate_key(record: MemoryRecord) -> str:
    return json.dumps(
        {
            "type": record.type,
            "fields": record.fields,
            "abstract": record.abstract,
            "body": record.body,
            "valid_from": record.valid_from or record.created,
            "author": record.author,
            "links": record.links,
            "provenance": record.provenance,
        },
        sort_keys=True,
        ensure_ascii=False,
    )

def _group_key(group: str) -> str:
    key = "".join(_WORDS.findall(group.lower()))
    return key[: -len(_PLURAL)] if key.endswith(_PLURAL) and len(key) > len(_PLURAL) else key

def _as_instant(value: str | None) -> str:
    if not value:
        return ""
    try:
        return timestamp.canonical(value)
    except ValueError:
        return ""


PROPOSAL_MERGE = reasoning.PROPOSAL_MERGE
PROPOSAL_SUPERSEDE = reasoning.PROPOSAL_SUPERSEDE
PROPOSAL_SPLIT = reasoning.PROPOSAL_SPLIT
PROPOSAL_DELETE = reasoning.PROPOSAL_DELETE
PROPOSAL_ACCEPT_STANDING = reasoning.PROPOSAL_ACCEPT_STANDING
PROPOSAL_CONFLICT_REVIEW = reasoning.PROPOSAL_CONFLICT_REVIEW
CONFLICT_OVERLAP_MIN = 0.5
NEGATION_CUES = frozenset({
    "not", "never", "no", "cannot", "cant", "dont", "doesnt", "isnt",
    "arent", "wasnt", "wont", "didnt",
})

PROPOSAL_ABSTRACT_REVIEW = reasoning.PROPOSAL_ABSTRACT_REVIEW

ACTION_DATE_NORMALISED = "date-normalised"
ACTION_DUPLICATE_MERGED = "duplicate-merged"
ACTION_LINK_ADDED = "link-added"
ACTION_WEIGHT_SETTLED = "weight-settled"
ACTION_CLUSTERED = "clustered"
ACTION_GROUP_MERGED = "group-merged"

PROPOSAL_ID_LENGTH = 12
REPORT_SUFFIX = ".md"
MERGED_SUFFIX = "-merged"
SECTION_PREFIX = "## "
GIT = "git"
_WORDS = re.compile(r"[0-9a-z]+")
_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "or", "of", "to", "is", "are", "for", "in", "on", "with", "that"}
)
_PLURAL = "s"

SECONDS_PER_HOUR = 3600.0
STAMP_FORMAT = "%Y%m%dT%H%M%S%f"

@dataclasses.dataclass(frozen=True)
class Proposal:
    kind: str
    targets: tuple[str, ...]
    reason: str
    evidence: str = ""

    @property
    def id(self) -> str:
        material = self.kind + "|" + "|".join(sorted(self.targets))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:PROPOSAL_ID_LENGTH]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "targets": list(self.targets),
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclasses.dataclass(frozen=True)
class Action:
    kind: str
    target: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "target": self.target, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class DreamReport:
    at: str
    actions: tuple[Action, ...]
    proposals: tuple[Proposal, ...]
    inspected: int
    path: str = ""
    decisions: tuple[Decision, ...] = ()
    withheld: tuple[str, ...] = ()
    committed: bool = False
    dream_id: str = ""
    review: reasoning.ReviewOutcome | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "at": self.at,
            "inspected": self.inspected,
            "actions": [action.as_dict() for action in self.actions],
            "proposals": [proposal.as_dict() for proposal in self.proposals],
            "decisions": [decision.as_dict() for decision in self.decisions],
            "withheld": list(self.withheld),
            "committed": self.committed,
            "path": self.path,
            "dream_id": self.dream_id,
            "review": _review_dict(self.review),
        }


class Dream:
    def __init__(self, store: Store, clock: Clock | None = None):
        self._store = store
        self._config = store.config
        self._clock = clock or store.clock
        from .database import Database
        from .docket import Docket

        self._database = Database(store.layout)
        self._docket = Docket(store, clock)

    def due(self, sessions_since: int) -> bool:
        last = self._docket.last_sleep()
        if last is None:
            return sessions_since >= self._config.manage.trigger_min_sessions
        elapsed_hours = (self._clock.now() - last).total_seconds() / SECONDS_PER_HOUR
        return (
            elapsed_hours >= self._config.manage.trigger_min_hours
            and sessions_since >= self._config.manage.trigger_min_sessions
        )

    def sleep(
        self, reasoner: reasoning.Reasoner | None = None, *, dream_id: str = ""
    ) -> DreamReport:
        records = self._store.records()
        hits, reads, last_access = self._usage()

        actions: list[Action] = []
        actions.extend(self._normalise_dates(records))
        actions.extend(self._settle_weights(records, reads, last_access))
        actions.extend(self._add_cooccurrence_links(records))
        actions.extend(self._merge_exact_duplicates(records))
        actions.extend(self._merge_near_duplicate_groups())
        actions.extend(self._cluster(self._store.records()))

        records = self._store.records()
        proposals = self._docket.proposals(records=records, hits=hits)
        decisions, withheld, review = self._docket.review(proposals, records, reasoner)
        settled = {decision.proposal_id for decision in decisions}

        report = DreamReport(
            at=self._clock.now().isoformat(),
            actions=tuple(actions),
            proposals=tuple(p for p in proposals if p.id not in settled),
            inspected=len(records),
            decisions=decisions,
            withheld=withheld,
            dream_id=dream_id,
            review=review,
        )
        report = dataclasses.replace(report, path=str(self._docket.write_report(report)))
        return dataclasses.replace(report, committed=self._docket.commit(report))

    def _usage(self) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
        """Lifetime counts decide what was never useful; only new reads earn weight, so one
        read is settled once however many sleeps follow it."""
        since = self._docket.last_sleep()
        with self._database.connect() as connection:
            log = AccessLog(connection)
            hits = log.counts()
            last_access = log.last_access()
            query = "SELECT name, COUNT(*) AS hits FROM access_log WHERE kind = ?"
            parameters: tuple[object, ...] = (KIND_READ,)
            if since is not None:
                query += " AND at > ?"
                parameters += (since.isoformat(),)
            reads = {
                str(row["name"]): int(row["hits"])
                for row in connection.execute(query + " GROUP BY name", parameters)
            }
        return hits, reads, last_access

    def _normalise_dates(self, records: list[MemoryRecord]) -> list[Action]:
        actions: list[Action] = []
        for record in records:
            wanted = {field: _as_instant(getattr(record, field)) for field in DATE_FIELDS}
            changed = {
                field: value
                for field, value in wanted.items()
                if value and value != getattr(record, field)
            }
            if not changed:
                continue
            for field, value in changed.items():
                setattr(record, field, value)
            self._rewrite(record)
            actions.append(Action(ACTION_DATE_NORMALISED, record.name, ", ".join(sorted(changed))))
        return actions

    def _settle_weights(
        self, records: list[MemoryRecord], reads: dict[str, int], last_access: dict[str, str]
    ) -> list[Action]:
        actions: list[Action] = []
        now = self._clock.now()
        for record in records:
            before = record.weight
            after = before + self._config.weight.boost_step * min(
                reads.get(record.name, 0), self._config.manage.max_boosts_per_sleep
            )
            if self._idle_days(record, last_access, now) >= self._config.weight.decay_after_days:
                after -= self._config.weight.decay_step
            after = min(self._config.weight.ceiling, max(self._config.weight.floor, after))
            if after == before:
                continue
            record.weight = after
            self._rewrite(record)
            actions.append(
                Action(ACTION_WEIGHT_SETTLED, record.name, f"{before:.2f} -> {after:.2f}")
            )
        return actions

    def _add_cooccurrence_links(self, records: list[MemoryRecord]) -> list[Action]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT at, agent, query, name FROM access_log "
                "WHERE query != '' AND kind = 'recall'"
            ).fetchall()
        together: dict[tuple[str, str], int] = {}
        by_query: dict[tuple[str, str, str], set[str]] = {}
        for row in rows:
            key = (str(row["at"]), str(row["agent"]), str(row["query"]))
            by_query.setdefault(key, set()).add(str(row["name"]))
        for names in by_query.values():
            for left in names:
                for right in names:
                    if left < right:
                        together[(left, right)] = together.get((left, right), 0) + 1

        known = {record.name: record for record in records}
        actions: list[Action] = []
        for (left, right), count in sorted(together.items()):
            if count < self._config.manage.link_cooccurrence_min:
                continue
            for source, target in ((left, right), (right, left)):
                record = known.get(source)
                if record is None or target not in known or target in record.links:
                    continue
                record.links.append(target)
                self._rewrite(record)
                actions.append(Action(ACTION_LINK_ADDED, source, target))
        return actions

    def _merge_exact_duplicates(self, records: list[MemoryRecord]) -> list[Action]:
        seen: dict[str, MemoryRecord] = {}
        actions: list[Action] = []
        for record in sorted(records, key=lambda item: (item.created, item.name)):
            if not record.is_active():
                continue
            key = _duplicate_key(record)
            original = seen.get(key)
            if original is None:
                seen[key] = record
                continue
            merged = self._store.merge_exact_duplicate(
                record, original, self._clock.timestamp()
            )
            if merged is not None:
                actions.append(Action(ACTION_DUPLICATE_MERGED, record.name, original.name))
        return actions

    def _docket_group_fields(self) -> dict[str, str]:
        return {
            schema.type: schema.group
            for schema in self._store.schemas.all()
            if schema.group and source_of(schema.group, self._config) == SOURCE_MENU
        }

    def _merge_near_duplicate_groups(self) -> list[Action]:
        """Two group directories that differ only in spelling are one topic split in two."""
        actions: list[Action] = []
        layout = self._store.layout
        for type_name, group_field in self._docket_group_fields().items():
            by_key: dict[str, list[str]] = {}
            for group in sorted(layout.groups_of(type_name)):
                by_key.setdefault(_group_key(group), []).append(group)
            for variants in by_key.values():
                if len(variants) < len(("one", "other")):
                    continue
                keeper = max(
                    variants, key=lambda group: (self._group_size(type_name, group), group)
                )
                for group in variants:
                    if group == keeper:
                        continue
                    for record in self._store.records():
                        if record.type == type_name and record.fields.get(group_field) == group:
                            self._move(record, keeper)
                            actions.append(
                                Action(ACTION_GROUP_MERGED, record.name, f"{group} -> {keeper}")
                            )
                    self._prune_empty_groups()
        return actions

    def _cluster(self, records: list[MemoryRecord]) -> list[Action]:
        """A directory holding many files that share vocabulary is a topic without a name yet;
        naming it is a directory operation, so it happens without a ruling."""
        actions: list[Action] = []
        group_fields = self._docket_group_fields()
        by_parent: dict[pathlib.Path, list[MemoryRecord]] = {}
        for record in records:
            if record.type not in group_fields:
                continue
            if record.is_active() and record.path is not None:
                by_parent.setdefault(record.path.parent, []).append(record)
        for _, flat in sorted(by_parent.items()):
            buckets: dict[str, set[str]] = {}
            for record in flat:
                for token in _tokens(f"{record.name} {record.abstract}"):
                    buckets.setdefault(token, set()).add(record.name)
            groups: dict[frozenset[str], set[str]] = {}
            for token, names in buckets.items():
                if len(names) < self._config.manage.cluster_min_files:
                    continue
                groups.setdefault(frozenset(names), set()).add(token)
            known = {record.name: record for record in flat}
            for grouped, shared in sorted(groups.items(), key=lambda group: sorted(group[0])):
                if len(shared) < self._config.manage.cluster_min_shared_tokens:
                    continue
                label = "-".join(sorted(shared))[: self._config.storage.slug_max_length]
                movable = []
                for name in sorted(grouped):
                    group_field = group_fields[known[name].type]
                    if known[name].fields.get(group_field, "") == label:
                        continue
                    if label in self._store.layout.groups_of(known[name].type):
                        continue
                    movable.append((known[name], group_field))
                for record, group_field in movable:
                    current = record.fields.get(group_field, "")
                    known[record.name] = self._move(record, label)
                    actions.append(Action(ACTION_CLUSTERED, record.name, f"{current} -> {label}"))
                self._prune_empty_groups()
        return actions

    def _prune_empty_groups(self) -> None:
        for type_name in self._docket_group_fields():
            for group in self._store.layout.groups_of(type_name):
                folder = self._store.layout.type_dir(type_name) / group
                if not any(folder.iterdir()):
                    folder.rmdir()

    def _move(self, record: MemoryRecord, group: str) -> MemoryRecord:
        return self._store.regroup(
            record.name, group, expected_source_hash=record.source_hash
        )

    def _group_size(self, type_name: str, group: str) -> int:
        folder = self._store.layout.type_dir(type_name) / group
        return len(list(folder.glob("*.md"))) if folder.is_dir() else 0

    def _idle_days(
        self, record: MemoryRecord, last_access: dict[str, str], now: dt.datetime
    ) -> float:
        stamp = last_access.get(record.name) or record.updated
        try:
            seen = timestamp.parse(stamp)
        except ValueError:
            seen = timestamp.parse(record.updated)
        return timestamp.days_between(now, seen)

    def _rewrite(self, record: MemoryRecord) -> None:
        self._store.write(record)