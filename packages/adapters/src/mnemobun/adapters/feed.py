"""Feeding: raw turns -> notes, gated by the perception trigger (P13.5c).

The adapter computes cheap features on the state.db read (user text vs tool
noise, length, novelty via the store's own search, repetition in the local
window). core.perception owns the math and the fire decision. Extraction runs
only when the trigger fires, through the caller's reasoner (the brain config
builds one for the idle task).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import pathlib
import re

from mnemobun.adapters.import_source import HermesSource, Turn
from mnemobun.core import perception
from mnemobun.core.distill import Ask, distill
from mnemobun.core.recall import Recall
from mnemobun.core.sessions import Message
from mnemobun.core.store import Store
from mnemobun.core.watermark import Watermark

RECENT_WINDOW = 20
CHARS_PER_TOKEN = 4


@dataclasses.dataclass(frozen=True)
class FeedReport:
    fired: bool
    signal: float
    quiet_seconds: float
    backlog_turns: int
    backlog_tokens: float
    sessions: tuple[str, ...] = ()
    written: int = 0
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def default_state_db() -> pathlib.Path:
    home = pathlib.Path(os.environ.get("HERMES_HOME") or pathlib.Path.home() / ".hermes")
    return home / "state.db"


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def features_for(turn: Turn, recent: list[str], store: Store) -> perception.TurnFeatures:
    """One turn's cheap features. The adapter computes, core scores."""
    text = f"{turn.user}\n{turn.assistant}".strip()
    normalized = _normalized(text)
    repetition = 1.0 if normalized and normalized in recent else 0.0
    novelty = 1.0
    query = turn.user.strip() or normalized
    if query:
        hits = Recall(store).recall(query, limit=1)
        best = max((hit.relevance for hit in hits), default=0.0)
        novelty = 1.0 - min(1.0, max(0.0, best))
    return perception.TurnFeatures(
        is_user_text=bool(turn.user.strip()),
        characters=len(text),
        novelty=novelty,
        repetition=repetition,
    )


def messages_for(backlog: list[Turn]) -> list[Message]:
    """D8: a turn is its user+assistant pair; present halves become messages."""
    messages: list[Message] = []
    for turn in backlog:
        if turn.user.strip():
            messages.append(Message(len(messages), "user", turn.user, turn.at))
        if turn.assistant.strip():
            messages.append(Message(len(messages), "assistant", turn.assistant, turn.at))
    return messages


def _quiet_seconds(turns: list[Turn], reference: dt.datetime) -> float:
    if not turns:
        return float("inf")
    stamps = []
    for turn in turns:
        try:
            stamps.append(dt.datetime.fromisoformat(turn.at))
        except ValueError:
            continue
    if not stamps:
        return float("inf")
    latest = max(stamps)
    return max(0.0, (reference - latest).total_seconds())


def run(
    store: Store,
    *,
    state_db: pathlib.Path | None = None,
    ask: Ask | None = None,
    now: dt.datetime | None = None,
) -> FeedReport:
    """Score the unprocessed backlog; extract only when the trigger fires.

    ask=None is decision-only: the report is produced, nothing is written.
    """
    config = store.config.usage
    source = HermesSource(str(state_db or default_state_db()))
    watermark = Watermark(store.layout, store.clock)
    turns = list(source.turns())
    by_session: dict[str, list[Turn]] = {}
    for turn in turns:
        by_session.setdefault(turn.session_id, []).append(turn)

    features: list[perception.TurnFeatures] = []
    recent: list[str] = []
    pending: dict[str, list[Turn]] = {}
    backlog_turns = 0
    backlog_chars = 0
    for session, session_turns in by_session.items():
        distilled = watermark.read(session).distilled
        backlog = session_turns[distilled:]
        if not backlog:
            continue
        pending[session] = backlog
        for turn in backlog:
            features.append(features_for(turn, recent[-RECENT_WINDOW:], store))
            recent.append(_normalized(f"{turn.user}\n{turn.assistant}"))
            backlog_turns += 1
            backlog_chars += len(turn.user) + len(turn.assistant)

    signal = perception.backlog_signal(features, config)
    quiet = _quiet_seconds(turns, now or store.clock.now())
    backlog_tokens = backlog_chars / CHARS_PER_TOKEN
    fired = perception.should_feed(
        signal=signal,
        quiet_seconds=quiet,
        backlog_tokens=backlog_tokens,
        backlog_turns=float(backlog_turns),
        config=config,
    )
    if not fired or not pending:
        return FeedReport(
            fired=False,
            signal=signal,
            quiet_seconds=quiet,
            backlog_turns=backlog_turns,
            backlog_tokens=backlog_tokens,
            reason="signal or quiet gate",
        )
    if ask is None:
        return FeedReport(
            fired=True,
            signal=signal,
            quiet_seconds=quiet,
            backlog_turns=backlog_turns,
            backlog_tokens=backlog_tokens,
            sessions=tuple(pending),
            reason="decision only: no reasoner",
        )
    written = 0
    for session, backlog in pending.items():
        report = distill(store, session, messages_for(backlog), ask)
        written += sum(len(batch.written) for batch in report.batches)
    return FeedReport(
        fired=True,
        signal=signal,
        quiet_seconds=quiet,
        backlog_turns=backlog_turns,
        backlog_tokens=backlog_tokens,
        sessions=tuple(pending),
        written=written,
        reason="fired",
    )
