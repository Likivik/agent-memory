"""The docket: the sleep ruling list.

Proposals are drafted here (merges, splits, supersessions, deletions, standing
accepts, conflict reviews), the reasoner rules the docket at the per-kind caps,
and the code applies the verdicts. A docket never removes a file; every decision
lands in the ledger, and the report records what was withheld.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import pathlib
import subprocess
import tempfile
import time

from . import reasoning, timestamp
from .clock import Clock
from .database import Database
from .dream import (
    GIT,
    MERGED_SUFFIX,
    PROPOSAL_ABSTRACT_REVIEW,
    PROPOSAL_ACCEPT_STANDING,
    PROPOSAL_CONFLICT_REVIEW,
    PROPOSAL_DELETE,
    PROPOSAL_MERGE,
    PROPOSAL_SPLIT,
    PROPOSAL_SUPERSEDE,
    REPORT_SUFFIX,
    SECTION_PREFIX,
    STAMP_FORMAT,
    DreamReport,
    Proposal,
    _contradiction_shape,
    _metric,
    _report_values,
    _seconds,
    _similarity,
    _tokens,
)
from .errors import FieldError, MemoryStoreError, NotFoundError, ValidationError
from .ledger import VERDICT_ACCEPTED, VERDICT_REJECTED, Decision, DecisionLedger
from .record import MemoryRecord
from .sessions import parse_pointer
from .standing import STANDING_ACCEPTED, STANDING_PROPOSED, add_conflict, set_standing
from .store import Store


class Docket:
    def __init__(self, store: Store, clock: Clock | None = None):
        self._store = store
        self._config = store.config
        self._clock = clock or store.clock
        self._database = Database(store.layout)

    def _rewrite(self, record: MemoryRecord) -> None:
        self._store.write(record)

    def review(
        self,
        proposals: list[Proposal],
        records: list[MemoryRecord],
        reasoner: reasoning.Reasoner | None,
    ) -> tuple[tuple[Decision, ...], tuple[str, ...], reasoning.ReviewOutcome | None]:
        """A reasoner may refuse anything and accept up to the per-kind cap; a verdict on
        something that is not open, or that an earlier verdict invalidated, is dropped."""
        if reasoner is None or not proposals:
            return (), (), None
        request = reasoning.prepare(proposals, records, self._review_limits())
        if isinstance(reasoner, reasoning.ManageToolReasoner):
            from .manage_toolkit import ManageReviewToolkit

            kit = ManageReviewToolkit(self._store, request)
            runtime = reasoner.review_converse(
                reasoning.native_instructions(), reasoning.native_material(request), kit
            )
            outcome = dataclasses.replace(
                kit.outcome(),
                duration_seconds=runtime.duration_seconds,
                startup_seconds=runtime.startup_seconds,
                model_wait_seconds=runtime.model_wait_seconds,
                mcp_seconds=runtime.mcp_seconds,
                shutdown_seconds=runtime.shutdown_seconds,
                model_requests=runtime.model_requests,
                agent_turns=runtime.agent_turns,
                input_tokens=runtime.input_tokens,
                cached_input_tokens=runtime.cached_input_tokens,
                output_tokens=runtime.output_tokens,
            )
            if not outcome.complete:
                raise ValidationError([FieldError("review", outcome.error)])
        else:
            outcome = reasoning.review_text(request, reasoner)
        apply_started = time.monotonic()
        open_now = {proposal.id: proposal for proposal in proposals}
        reviewed = {proposal.id: proposal for proposal in request.proposals}
        caps = self._caps()
        accepted: dict[str, int] = {}
        decisions: list[Decision] = []
        withheld: list[str] = []
        for verdict in outcome.verdicts:
            proposal = open_now.get(verdict.proposal_id)
            if proposal is None:
                continue
            if verdict.accept and accepted.get(proposal.kind, 0) >= caps.get(proposal.kind, 0):
                withheld.append(proposal.id)
                continue
            try:
                decisions.append(
                    self.decide(
                        proposal.id,
                        accept=verdict.accept,
                        verdict=verdict,
                        expected_sources=reviewed[proposal.id].sources,
                    )
                )
            except MemoryStoreError:
                withheld.append(proposal.id)
                continue
            if verdict.accept:
                accepted[proposal.kind] = accepted.get(proposal.kind, 0) + 1
        outcome = dataclasses.replace(outcome, apply_seconds=time.monotonic() - apply_started)
        return tuple(decisions), tuple(withheld), outcome

    def _review_limits(self) -> reasoning.ReviewLimits:
        manage = self._config.manage
        executor = self._config.executor
        return reasoning.ReviewLimits(
            max_steps=manage.review_max_steps,
            max_tool_calls=manage.review_max_tool_calls,
            timeout_seconds=executor.manage.timeout_seconds or executor.timeout_seconds,
            tool_result_chars=manage.review_tool_result_chars,
            evidence_chars=manage.review_evidence_chars,
            raw_session_evidence=manage.review_raw_session_evidence,
        )

    def _caps(self) -> dict[str, int]:
        manage = self._config.manage
        return {
            PROPOSAL_MERGE: manage.max_merges_per_sleep,
            PROPOSAL_SUPERSEDE: manage.max_supersedes_per_sleep,
            PROPOSAL_SPLIT: manage.max_splits_per_sleep,
            PROPOSAL_DELETE: manage.max_deletes_per_sleep,
            PROPOSAL_ACCEPT_STANDING: manage.max_accepts_per_sleep,
            PROPOSAL_CONFLICT_REVIEW: manage.max_conflicts_per_sleep,
            PROPOSAL_ABSTRACT_REVIEW: len(self._store.records()),
        }

    def proposals(
        self, records: list[MemoryRecord] | None = None, hits: dict[str, int] | None = None
    ) -> list[Proposal]:
        """Everything worth a ruling that nobody has ruled on yet. Pure: nothing is written."""
        inspected = self._store.records() if records is None else records
        if hits is not None:
            counts = hits
        else:
            from .access_log import AccessLog

            with self._database.connect() as connection:
                log = AccessLog(connection)
                counts = log.counts()

        decided = self._ledger().decided()
        drafted: list[Proposal] = []
        drafted.extend(self._propose_merges(inspected))
        drafted.extend(self._propose_splits(inspected))
        drafted.extend(self._propose_abstract_review(inspected))
        drafted.extend(self._propose_deletions(inspected, counts))
        drafted.extend(self._propose_standing_accepts(inspected))
        drafted.extend(self._propose_conflict_reviews(inspected))
        return [proposal for proposal in drafted if proposal.id not in decided]

    def decide(
        self,
        proposal_id: str,
        accept: bool,
        text: str = "",
        verdict: reasoning.Verdict | None = None,
        *,
        expected_sources: tuple[reasoning.ReviewSource, ...] = (),
    ) -> Decision:
        """Rule on one proposal. Acceptance applies it through the write path."""
        proposal = self._open(proposal_id)
        self._require_sources(expected_sources)
        content = verdict or reasoning.Verdict(proposal_id, accept, text=text)
        detail = self._apply(proposal, content, expected_sources) if accept else ""
        return self._ledger().append(
            Decision(
                proposal_id=proposal.id,
                verdict=VERDICT_ACCEPTED if accept else VERDICT_REJECTED,
                at=self._clock.now().isoformat(),
                detail=detail,
            )
        )

    def _require_sources(self, sources: tuple[reasoning.ReviewSource, ...]) -> None:
        for source in sources:
            current = self._store.find(source.name)
            if current is None or not current.is_active():
                raise ValidationError(
                    [FieldError("proposal", f"source {source.name} is no longer active")]
                )
            if current.source_hash != source.source_hash:
                raise ValidationError(
                    [FieldError("proposal", f"source {source.name} changed during review")]
                )

    def _open(self, proposal_id: str) -> Proposal:
        for proposal in self.proposals():
            if proposal.id == proposal_id:
                return proposal
        raise NotFoundError(f"no open proposal {proposal_id}")

    def _apply(
        self,
        proposal: Proposal,
        verdict: reasoning.Verdict,
        sources: tuple[reasoning.ReviewSource, ...] = (),
    ) -> str:
        expected = {source.name: source.source_hash for source in sources}
        if proposal.kind == PROPOSAL_MERGE:
            return self._merge(proposal, verdict, expected)
        if proposal.kind == PROPOSAL_SUPERSEDE:
            return self._supersede(proposal, expected)
        if proposal.kind == PROPOSAL_SPLIT:
            return self._split(proposal, verdict, expected)
        if proposal.kind == PROPOSAL_DELETE:
            return self._delete(proposal, expected)
        if proposal.kind == PROPOSAL_ACCEPT_STANDING:
            return self._accept_standing(proposal)
        if proposal.kind == PROPOSAL_CONFLICT_REVIEW:
            return self._apply_conflict_review(proposal)
        return self._rewrite_abstract(proposal, verdict.text, expected)

    def _accept_standing(self, proposal: Proposal) -> str:
        """Deterministic apply: the reasoner only chose the docket item."""
        target = proposal.targets[0]
        written = set_standing(self._store, target, STANDING_ACCEPTED, cause="sleep_menu")
        return f"standing of {written.name} -> accepted"

    def _merge(
        self, proposal: Proposal, verdict: reasoning.Verdict, expected: dict[str, str]
    ) -> str:
        """The reasoner writes the knowledge; the library computes time, identity, evidence."""
        if not verdict.abstract.strip() or not verdict.body.strip():
            raise ValidationError(
                [FieldError("body", "accepting a merge needs the merged abstract and body")]
            )
        entries = [self._entry(name) for name in proposal.targets]
        keeper = max(entries, key=lambda record: (len(record.body), record.created, record.name))
        name = keeper.name + MERGED_SUFFIX
        if self._store.find(name) is not None:
            name += "-" + self._clock.stamp().lower()
        merged = self._store.merge(
            [record.name for record in entries],
            verdict.abstract,
            verdict.body,
            name=name,
            expected_source_hashes=expected,
        )
        return f"merged into {merged.name}"

    def _supersede(self, proposal: Proposal, expected: dict[str, str]) -> str:
        entries = [self._entry(name) for name in proposal.targets]
        keeper = max(entries, key=lambda record: (len(record.body), record.created, record.name))
        for record in entries:
            if record.name == keeper.name:
                continue
            self._store.supersede(
                record.name,
                keeper.name,
                expected_source_hash=expected.get(record.name),
                expected_successor_hash=expected.get(keeper.name),
            )
        return f"kept {keeper.name}"

    def _split(
        self, proposal: Proposal, verdict: reasoning.Verdict, expected: dict[str, str]
    ) -> str:
        """The original keeps its name as the first part; every other part is a new file."""
        parts = [part for part in verdict.parts if part.abstract.strip() and part.body.strip()]
        if len(parts) < len(("first", "second")):
            raise ValidationError(
                [FieldError("parts", "accepting a split needs at least two parts with content")]
            )
        original = self._entry(proposal.targets[0])
        original.source_hash = expected.get(original.name, original.source_hash)
        own = set(original.provenance)
        now = self._clock.timestamp()
        names = []
        for index, part in enumerate(parts):
            provenance = [pointer for pointer in part.provenance if pointer in own] or list(own)
            if index == 0:
                original.abstract = part.abstract.strip()
                original.body = part.body.strip()
                original.provenance = provenance
                original.updated = now
                self._rewrite(original)
                names.append(original.name)
                continue
            written = self._store.record(
                type=original.type,
                name=f"{original.name}-{index}",
                fields=dict(original.fields),
                abstract=part.abstract.strip(),
                body=part.body.strip(),
                links=list(original.links),
                usage=original.usage,
                importance=original.importance,
                valid_from=original.valid_from,
                provenance=provenance,
                create_group=True,
            )
            names.append(written.name)
        return "split into " + ", ".join(names)

    def _delete(self, proposal: Proposal, expected: dict[str, str]) -> str:
        name = proposal.targets[0]
        removed = self._store.delete(name, expected_source_hash=expected.get(name))
        return f"marked {removed.name} invalid"

    def _rewrite_abstract(self, proposal: Proposal, text: str, expected: dict[str, str]) -> str:
        if not text.strip():
            raise ValidationError(
                [FieldError("text", "accepting an abstract review needs the replacement abstract")]
            )
        record = self._entry(proposal.targets[0])
        record.source_hash = expected.get(record.name, record.source_hash)
        record.abstract = text.strip()
        self._rewrite(record)
        return f"rewrote the abstract of {record.name}"

    def _entry(self, name: str) -> MemoryRecord:
        record = self._store.find(name)
        if record is None:
            raise NotFoundError(f"no memory named {name}")
        return record

    def _ledger(self) -> DecisionLedger:
        return DecisionLedger(self._store.layout)

    def _apply_conflict_review(self, proposal: Proposal) -> str:
        target, peer = proposal.targets[0], proposal.targets[1]
        written = add_conflict(self._store, target, peer)
        return f"conflict edge {written.name} <-> {peer}"

    def _propose_merges(self, records: list[MemoryRecord]) -> list[Proposal]:
        """Two entries saying one thing: supersede when one already holds the other, merge
        when each holds something the other lacks and one file could hold both."""
        active = [record for record in records if record.is_active()]
        proposals: list[Proposal] = []
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                overlap = _similarity(left, right)
                if overlap < self._config.manage.merge_proposal_similarity:
                    continue
                first, second = _tokens(left.abstract), _tokens(right.abstract)
                if first <= second or second <= first:
                    kind = PROPOSAL_SUPERSEDE
                elif left.type == right.type:
                    kind = PROPOSAL_MERGE
                else:
                    continue
                proposals.append(
                    Proposal(
                        kind=kind,
                        targets=(left.name, right.name),
                        reason="abstracts overlap above the proposal threshold",
                        evidence=f"similarity={overlap:.2f}",
                    )
                )
        return proposals

    def _propose_splits(self, records: list[MemoryRecord]) -> list[Proposal]:
        """A file with several sections drawn from several conversations will go stale in
        pieces, and a file is the invalidation atom (Invariant 7)."""
        minimum = self._config.manage.split_min_sections
        proposals: list[Proposal] = []
        for record in records:
            if not record.is_active():
                continue
            sections = sum(
                1 for line in record.body.splitlines() if line.startswith(SECTION_PREFIX)
            )
            sessions = {
                pointer.session
                for pointer in (parse_pointer(item) for item in record.provenance)
                if pointer is not None
            }
            if sections >= minimum and len(sessions) >= len(("one", "other")):
                proposals.append(
                    Proposal(
                        kind=PROPOSAL_SPLIT,
                        targets=(record.name,),
                        reason="one file holds parts that will expire separately",
                        evidence=f"sections={sections}, sessions={len(sessions)}",
                    )
                )
        return proposals

    def _propose_abstract_review(self, records: list[MemoryRecord]) -> list[Proposal]:
        limit = self._config.storage.abstract_max_chars
        return [
            Proposal(
                kind=PROPOSAL_ABSTRACT_REVIEW,
                targets=(record.name,),
                reason="abstract is too thin to recognise this memory by",
                evidence=f"words={len(_tokens(record.abstract))}",
            )
            for record in records
            if record.is_active()
            and (
                len(_tokens(record.abstract)) < self._config.manage.abstract_min_words
                or len(record.abstract) > limit
            )
        ]

    def _propose_deletions(
        self, records: list[MemoryRecord], hits: dict[str, int]
    ) -> list[Proposal]:
        return [
            Proposal(
                kind=PROPOSAL_DELETE,
                targets=(record.name,),
                reason="never recalled and already at the usage floor",
                evidence=f"usage={record.usage:.2f}",
            )
            for record in records
            if record.is_active()
            and hits.get(record.name, 0) == 0
            and record.usage <= self._config.usage.floor
        ]

    def _propose_standing_accepts(self, records: list[MemoryRecord]) -> list[Proposal]:
        """Docket-only accept path (design decision 4): a `proposed` claim becomes `accepted`
        only when a sleep reasoner or the user rules on it — never automatically."""
        return [
            Proposal(
                kind=PROPOSAL_ACCEPT_STANDING,
                targets=(record.name,),
                reason="new claim awaits confirmation",
                evidence=record.abstract,
            )
            for record in records
            if record.type == "claim" and record.standing == STANDING_PROPOSED
        ]

    def _propose_conflict_reviews(
        self, records: list[MemoryRecord]
    ) -> list[Proposal]:
        """Draft likely contradictions for a ruling (v2 of decision 3): deterministic
        pair-finding — same negation polarity flip with high token overlap — while the
        sleep reasoner DECIDES and code applies the explicit conflict edge. No NLI
        model in core; the judgement is the reasoner's, the record-keeping is ours."""
        claims = [
            record
            for record in records
            if record.type == "claim" and record.standing == STANDING_ACCEPTED
        ]
        proposals: list[Proposal] = []
        seen: set[tuple[str, str]] = set()
        for index, first in enumerate(claims):
            for second in claims[index + 1:]:
                if not _contradiction_shape(first, second):
                    continue
                names = sorted((first.name, second.name))
                pair = (names[0], names[1])
                if pair in seen:
                    continue
                seen.add(pair)
                proposals.append(Proposal(
                    kind=PROPOSAL_CONFLICT_REVIEW,
                    targets=(first.name, second.name),
                    reason="same subject, opposite negation polarity",
                    evidence=f"{first.abstract} || {second.abstract}",
                ))
        return proposals

    def write_report(self, report: DreamReport) -> str:
        folder = self._store.layout.dream_reports
        folder.mkdir(parents=True, exist_ok=True)
        filename = (
            f"auto-{report.dream_id}{REPORT_SUFFIX}"
            if report.dream_id
            else (self._clock.stamp() + REPORT_SUFFIX)
        )
        path = folder / filename
        lines = [
            f"# dream report {report.at}",
            "",
            f"inspected: {report.inspected}",
            f"dream_id: {report.dream_id}" if report.dream_id else "",
            "",
            "## applied",
            "",
        ]
        lines.extend(
            f"- {action.kind}: {action.target} — {action.detail}" for action in report.actions
        )
        lines.extend(["", "## decided", ""])
        lines.extend(
            f"- {decision.proposal_id} {decision.verdict}"
            + (f" — {decision.detail}" if decision.detail else "")
            for decision in report.decisions
        )
        lines.extend(["", "## proposals (open)", ""])
        lines.extend(
            f"- {proposal.kind}: {', '.join(proposal.targets)} — {proposal.reason}"
            f" ({proposal.evidence})"
            for proposal in report.proposals
        )
        if report.withheld:
            lines.extend(["", "## withheld (over the cap or refused by the write path)", ""])
            lines.extend(f"- {proposal_id}" for proposal_id in report.withheld)
        if report.review is not None:
            lines.extend(["", "## review execution", ""])
            lines.extend(
                [
                    f"- submitted: {str(report.review.submitted).lower()}",
                    f"- complete: {str(report.review.complete).lower()}",
                    f"- rounds: {report.review.rounds}",
                    f"- tool_calls: {report.review.tool_calls}",
                    f"- duration_seconds: {report.review.duration_seconds:.3f}",
                    f"- startup_seconds: {_seconds(report.review.startup_seconds)}",
                    f"- model_wait_seconds: {_seconds(report.review.model_wait_seconds)}",
                    f"- mcp_seconds: {_seconds(report.review.mcp_seconds)}",
                    f"- shutdown_seconds: {_seconds(report.review.shutdown_seconds)}",
                    f"- apply_seconds: {report.review.apply_seconds:.3f}",
                    f"- model_requests: {_metric(report.review.model_requests)}",
                    f"- agent_turns: {_metric(report.review.agent_turns)}",
                    f"- input_tokens: {_metric(report.review.input_tokens)}",
                    f"- cached_input_tokens: {_metric(report.review.cached_input_tokens)}",
                    f"- output_tokens: {_metric(report.review.output_tokens)}",
                    _report_values(
                        "evidence_reads",
                        (f"{proposal}/{name}" for proposal, name in report.review.evidence_reads),
                    ),
                    _report_values(
                        "provenance_reads",
                        (
                            f"{proposal}/{name}/{pointer}"
                            for proposal, name, pointer in report.review.provenance_reads
                        ),
                    ),
                    _report_values(
                        "tool_trace",
                        (
                            f"{name}{'!error' if failed else ''}"
                            for name, failed in report.review.tool_trace
                        ),
                    ),
                ]
            )
        rendered = "\n".join(lines) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as temporary:
            temporary.write(rendered)
            staged = pathlib.Path(temporary.name)
        try:
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)
        return str(path)

    def commit(self, report: DreamReport) -> bool:
        """One sleep, one commit: the audit trail a human reviews from outside the loop."""
        if not self._config.manage.git_commit:
            return False
        root = str(self._store.root)
        try:
            inside = subprocess.run(
                [GIT, "-C", root, "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
            if inside.returncode != 0 or inside.stdout.strip() != "true":
                return False
            subprocess.run(
                [GIT, "-C", root, "add", "-A", "--", root], check=True, capture_output=True
            )
            done = subprocess.run(
                [GIT, "-C", root, "commit", "-q", "-m", f"sleep {report.at}", "--", root],
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return done.returncode == 0

    def _last_sleep(self) -> dt.datetime | None:
        folder = self._store.layout.dream_reports
        reports = sorted(folder.glob("*" + REPORT_SUFFIX)) if folder.exists() else []
        found: list[dt.datetime] = []
        for path in reports:
            try:
                found.append(dt.datetime.strptime(path.stem, STAMP_FORMAT).replace(tzinfo=dt.UTC))
            except ValueError:
                try:
                    heading = path.read_text(encoding="utf-8").splitlines()[0]
                    found.append(timestamp.parse(heading.removeprefix("# dream report ").strip()))
                except (OSError, IndexError, ValueError):
                    continue
        return max(found) if found else None

    def last_sleep(self) -> dt.datetime | None:
        """Latest completed report, including stable-id reports from automatic workers."""
        return self._last_sleep()
