"""In-process Hermes provider (P3, design doc v1.2 §11 / decisions 4–7).

The provider is the only component that speaks both dialects: it presents the store as the
Hermes MemoryProvider surface (prefetch / sync_turn / verify) and backs it entirely with
core calls — no MCP hop, no LLM in the write path. `agent.memory_provider` is the host-side
base class; it is imported defensively so this package stays installable without Hermes.

Semantics fixed by the design:
- prefetch: accepted+proposed claims first (top-k, newest updated), then recent events,
  hard-capped at `prefetch_budget_bytes` — injection is a floor the provider may fill,
  never overflow (decision 7).
- sync_turn: appends the raw turn as an `event` with provenance; NOTHING else. Claims are
  written by the agent's explicit `memory_record` calls (no separate extraction pipeline,
  constraint 1) and enter as `proposed` — acceptance stays with the Dream docket or the
  user (decision 4, already enforced by the store's `_spec_standing`).
- verify: binds the host reasoner (a str->str callable) as the audit labeler (decision 8);
  core stays reasoner-free.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Protocol, runtime_checkable

from mnemobun.core.audit import LABEL_ABSTAIN
from mnemobun.core.audit import verify as audit_verify
from mnemobun.core.recall import Recall
from mnemobun.core.record import STANDING_ACCEPTED, STANDING_PROPOSED
from mnemobun.core.store import Store

PROVIDER_NAME = "mnemobun"
INJECTION_FLOOR_BYTES = 1500  # named here and in ProviderConfig; config value wins
PROVENANCE_TURN = "sync_turn"


@runtime_checkable
class MemoryProviderProtocol(Protocol):
    """The Hermes host-side provider shape (defensive — Hermes may not be installed)."""

    def prefetch(self, query: str, *, session_id: str = "") -> str: ...
    def sync_turn(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> None: ...


def _base_class() -> tuple[bool, type | None]:
    try:  # pragma: no cover - depends on the host environment
        from agent.memory_provider import MemoryProvider
    except Exception:
        return False, None
    return True, MemoryProvider


@dataclasses.dataclass
class HermesMemoryProvider:
    """MemoryProvider implementation backed by this fork's core. See module docstring."""

    store: Store
    reasoner: Any | None = None  # a str->str callable; None => verify abstains

    def __post_init__(self) -> None:
        available, base = _base_class()
        self._is_available = available or True  # usable standalone; Hermes just gets richer
        self._base = base
        self.last_recall_count = 0  # lines the last prefetch injected (recall indicator)

    # -- lifecycle ---------------------------------------------------------
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        return self.store.layout.root.exists()

    def late_init(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: object) -> bool:
        self._session_id = session_id
        return self.is_available()

    # -- read side ---------------------------------------------------------
    def system_prompt_block(self) -> str:
        return (
            "Memory is available. Verify claims you rely on with memory_verify;"
            " record durable beliefs as claims (they start `proposed` and are accepted"
            " only after a ruling)."
        )

    def feed_tick(self, *args: object, **kwargs: object) -> dict[str, object]:
        """Idle task (feed): score the backlog, extract when the trigger fires."""
        from mnemobun.adapters import feed
        from mnemobun.executor import distiller as distiller_module
        from mnemobun.executor import model_resolution, selection

        route = model_resolution.route_for(self.store)
        if route is None:
            result = feed.run(self.store, ask=None).as_dict()
            result["needs_model"] = True
            result["reason"] = model_resolution.NEEDS_MODEL
            return result
        ask = None
        if self.reasoner is not None:  # host-injected (ctx.llm); None = decision-only
            try:
                ask = distiller_module.distiller(
                    selection.resolve(self.store.config.executor, "write"),
                    store=self.store,
                    ask=self.reasoner,
                )
            except Exception:
                ask = None  # decision-only report instead of a dead idle task
        result = feed.run(self.store, ask=ask).as_dict()
        result["model"] = route.label()
        return result

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        settings = self.store.config.provider
        budget = settings.prefetch_budget_bytes or INJECTION_FLOOR_BYTES
        sections = self._claims_block(settings.prefetch_top_k)
        if query.strip():
            for hit in Recall(self.store).recall(query, log=False):
                if getattr(hit, "type", "") == "event":
                    continue  # raw turns are the log, not memory; recalling them is noise
                line = f"- {hit.name}: {hit.abstract}"
                sections.append(("recall", line))
        out: list[str] = []
        used = 0
        for _, line in sections:
            encoded = line.encode("utf-8")
            if used + len(encoded) + 1 > budget:
                break
            out.append(line)
            used += len(encoded) + 1
        self.last_recall_count = len(out)
        return "\n".join(out)

    def _claims_block(self, top_k: int) -> list[tuple[str, str]]:
        claims = [
            record
            for record in self.store.records()
            if record.type == "claim"
            and record.standing in (STANDING_ACCEPTED, STANDING_PROPOSED)
        ]
        claims.sort(key=lambda record: record.updated, reverse=True)
        if not claims:  # no claims, no header: an empty block is noise on every turn
            return []
        lines = ["Standing claims:"]
        for record in claims[:top_k]:
            marker = "" if record.standing == STANDING_ACCEPTED else " (proposed)"
            lines.append(f"- {record.name}{marker}: {record.abstract}")
        return [("claims", line) for line in lines]

    # -- write side --------------------------------------------------------
    def sync_turn(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> dict[str, Any]:
        """Append the raw turn. Identity and dedupe live in TurnCaptureService."""
        from mnemobun.executor.capture import TurnCaptureService

        return TurnCaptureService(self.store).capture(
            user_content, assistant_content, session_id=session_id
        )

    # -- audit side --------------------------------------------------------
    def verify(self, draft: str, query: str, *, agent: str = PROVIDER_NAME) -> dict[str, Any]:
        if self.reasoner is None:
            result = audit_verify(self.store, draft, query, labeler=None, agent=agent)
            if result["label"] == LABEL_ABSTAIN and result["reason"] is None:
                result["reason"] = "no labeler bound"
            return result
        return audit_verify(self.store, draft, query, labeler=self.reasoner, agent=agent)

    # -- sleep / dream wiring (P6) ------------------------------------------
    def sleep_due(self, sessions_since: int) -> bool:
        from mnemobun.core.dream import Dream

        return Dream(self.store).due(sessions_since)

    def run_sleep(self, sessions_since: int, *, dream_id: str = "") -> dict[str, Any]:
        """Run a Dream sleep with the bound reasoner (decision 5: docket-capped).

        The reasoner only rules on the drafted docket; deterministic code applies.
        With no reasoner bound, the deterministic half still runs and proposals
        stay open for the next ruling (never auto-accepted)."""
        from mnemobun.core.dream import Dream

        manage = Dream(self.store)
        if not manage.due(sessions_since) and not dream_id:
            return {"skipped": "not due"}
        reasoner = self.reasoner
        report = manage.sleep(reasoner, dream_id=dream_id)
        return report.as_dict() if hasattr(report, "as_dict") else {"report": str(report)}

    # -- MCP passthrough (P4 mapping) --------------------------------------
    def get_tool_schemas(self) -> list[dict[str, Any]]:
        from mnemobun.mcp.tools import catalogue

        return catalogue()

    def handle_tool_call(self, name: str, args: dict[str, Any], **kwargs: object) -> Any:
        from mnemobun.mcp.tools import dispatch

        return dispatch(self.store, name, args)
