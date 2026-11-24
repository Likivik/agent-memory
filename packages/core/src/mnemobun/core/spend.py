"""Spend guard: hard bounds on calls + input tokens; USD is a soft estimate.

Hard, enforced limits are what we control: the number of LLM calls per run and
the input tokens we send per day. USD is estimated
(chars over chars-per-token times a per-token price when one is known) and
never gates. The ledger is append-only signed lines; the day window is their
sum, so a run's reservation is replaced by its actuals at finish and a crashed
run keeps counting its reservation (the safe direction: underspend).
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import datetime as dt
import json
import math
from collections.abc import Iterator

from mnemobun.core.config import Config
from mnemobun.core.locking import store_lock
from mnemobun.core.store import Store

_CURRENT_RUN: contextvars.ContextVar[str] = contextvars.ContextVar("mnemobun_spend_run", default="")


@contextlib.contextmanager
def run_scope(
    store: Store, *, projection: Projection, run_id: str, actor: str
) -> Iterator[None]:
    """Book the run, attribute its calls to it, net the reservation at the end."""
    guard_run(store, projection, run_id=run_id, actor=actor)
    token = _CURRENT_RUN.set(run_id)
    try:
        yield
    finally:
        _CURRENT_RUN.reset(token)
        finish_run(store, run_id=run_id, projection=projection)

KIND_RESERVE = "reserve"
KIND_CALL = "call"
KIND_FINISH = "finish"
KIND_REFUSED = "refused"

REFUSAL = (
    "spend refused: {reason}; projected {calls} calls / "
    "{tokens} tokens, remaining {remaining}"
)


class SpendRefused(Exception):
    """A run or call that would cross a hard bound. Message text is a contract."""


@dataclasses.dataclass(frozen=True)
class Projection:
    calls: int
    in_tokens: int
    out_tokens: int = 0
    est_usd: float = 0.0
    priced: bool = False

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def project(
    *,
    chars: int,
    calls: int,
    config: Config,
    pricing: dict[str, float] | None = None,
    model: str = "",
) -> Projection:
    """Estimate one run. Unknown pricing = unpriced (est_usd stays 0.0)."""
    tokens = chars // config.write.chars_per_token
    price = (pricing or {}).get(model)
    est_usd = tokens * price if price else 0.0
    return Projection(
        calls=calls,
        in_tokens=tokens,
        est_usd=est_usd,
        priced=bool(price),
    )


def _ledger_path(store: Store):
    return store.root / ".state" / "spend-ledger.jsonl"


def _append(store: Store, line: dict[str, object]) -> None:
    path = _ledger_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": store.clock.now().isoformat(), **line}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _lines(store: Store) -> list[dict[str, object]]:
    path = _ledger_path(store)
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        with _ignore_bad(raw):
            entries.append(json.loads(raw))
    return entries


class _ignore_bad:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, (ValueError, KeyError))


def _in_window(stamp: str, *, day: bool, now: dt.datetime) -> bool:
    when = dt.datetime.fromisoformat(stamp)
    if day:
        return (when.year, when.month, when.day) == (now.year, now.month, now.day)
    return (when.year, when.month) == (now.year, now.month)


def current_run_id() -> str:
    """The run scope this call sits inside, if any."""
    return _CURRENT_RUN.get()


def usage(store: Store, *, day: bool) -> dict[str, float]:
    """Signed sums over the window: reservations net out at finish."""
    calls = 0.0
    tokens = 0.0
    usd = 0.0
    for line in _lines(store):
        if line.get("kind") == KIND_REFUSED:
            continue
        if not _in_window(str(line["at"]), day=day, now=store.clock.now()):
            continue
        sign = -1.0 if line["kind"] == KIND_FINISH else 1.0
        calls += sign * float(str(line.get("calls", 0)))
        tokens += sign * float(str(line.get("in_tokens", 0)))
        usd += sign * float(str(line.get("est_usd", 0.0)))
    return {"calls": calls, "in_tokens": tokens, "est_usd": usd}


def _refuse(reason: str, calls: float, tokens: float, remaining: float) -> SpendRefused:
    return SpendRefused(
        REFUSAL.format(reason=reason, calls=calls, tokens=tokens, remaining=remaining)
    )


def guard_run(store: Store, projection: Projection, *, run_id: str, actor: str) -> None:
    """Book the projection; refuse the run if it cannot fit the hard bounds."""
    with store_lock(store.layout):
        _guard_run_locked(store, projection, run_id=run_id, actor=actor)


def _guard_run_locked(store: Store, projection: Projection, *, run_id: str, actor: str) -> None:
    config = store.config.budget
    if projection.calls > config.max_calls_per_run:
        raise _refuse(
            "max_calls_per_run",
            projection.calls,
            projection.in_tokens,
            config.max_calls_per_run,
        )
    today = usage(store, day=True)
    remaining_tokens = config.max_tokens_per_day - today["in_tokens"]
    if projection.in_tokens > remaining_tokens:
        raise _refuse(
            "max_tokens_per_day",
            projection.calls,
            projection.in_tokens,
            max(0.0, remaining_tokens),
        )
    _append(
        store,
        {
            "kind": KIND_RESERVE,
            "run_id": run_id,
            "actor": actor,
            "calls": projection.calls,
            "in_tokens": projection.in_tokens,
            "est_usd": projection.est_usd,
        },
    )


def open_reserve(store: Store, run_id: str) -> dict[str, float]:
    """This run's reservation not yet netted out (reserve minus finish)."""
    calls = 0.0
    tokens = 0.0
    for line in _lines(store):
        if line.get("run_id") != run_id:
            continue
        if line["kind"] == KIND_RESERVE:
            calls += float(str(line.get("calls", 0)))
            tokens += float(str(line.get("in_tokens", 0)))
        elif line["kind"] == KIND_FINISH:
            calls -= float(str(line.get("calls", 0)))
            tokens -= float(str(line.get("in_tokens", 0)))
    return {"calls": calls, "in_tokens": tokens}


def record_call(
    store: Store, *, prompt_chars: int, run_id: str = "", model: str = ""
) -> None:
    """One real request about to be sent. Refuses past the hard bounds."""
    run_id = run_id or _CURRENT_RUN.get() or f"adhoc-{store.clock.now().isoformat()}"
    with store_lock(store.layout):
        _record_call_locked(store, run_id=run_id, prompt_chars=prompt_chars, model=model)


def _record_call_locked(store: Store, *, run_id: str, prompt_chars: int, model: str = "") -> None:
    config = store.config.budget
    tokens = prompt_chars // store.config.write.chars_per_token
    own = open_reserve(store, run_id)
    today = usage(store, day=True)
    # the run's own reservation already covers its calls; do not double-count
    adjusted_tokens = today["in_tokens"] - own["in_tokens"]
    run_calls = sum(
        float(str(line.get("calls", 0)))
        for line in _lines(store)
        if line.get("kind") == KIND_CALL and line.get("run_id") == run_id
    )
    if run_calls >= config.max_calls_per_run:
        raise _refuse("max_calls_per_run", run_calls, today["in_tokens"], config.max_calls_per_run)
    if adjusted_tokens + tokens > config.max_tokens_per_day:
        raise _refuse(
            "max_tokens_per_day",
            run_calls,
            adjusted_tokens + tokens,
            max(0.0, config.max_tokens_per_day - adjusted_tokens),
        )
    _append(
        store,
        {
            "kind": KIND_CALL,
            "run_id": run_id,
            "model": model,
            "calls": 1,
            "in_tokens": tokens,
        },
    )


def finish_run(store: Store, *, run_id: str, projection: Projection) -> None:
    """Net out the reservation; the calls already counted stay counted."""
    with store_lock(store.layout):
        _append(
        store,
        {
            "kind": KIND_FINISH,
            "run_id": run_id,
            "calls": projection.calls,
            "in_tokens": projection.in_tokens,
            "est_usd": projection.est_usd,
        },
    )


def open_reservations(store: Store, *, hours: float = 0.0) -> list[dict[str, object]]:
    """Reservations not yet netted out; optionally only those older than hours."""
    import datetime as _dt

    cutoff = store.clock.now() - _dt.timedelta(hours=hours)
    rows: dict[str, dict[str, float]] = {}
    stamps: dict[str, str] = {}
    for line in _lines(store):
        run_id = str(line.get("run_id") or "")
        if not run_id:
            continue
        row = rows.setdefault(run_id, {"calls": 0.0, "in_tokens": 0.0})
        stamps.setdefault(run_id, str(line.get("at") or ""))
        if line["kind"] == KIND_RESERVE:
            row["calls"] += float(str(line.get("calls", 0)))
            row["in_tokens"] += float(str(line.get("in_tokens", 0)))
        elif line["kind"] == KIND_FINISH:
            row["calls"] -= float(str(line.get("calls", 0)))
            row["in_tokens"] -= float(str(line.get("in_tokens", 0)))
    out = []
    for run_id, row in rows.items():
        if row["calls"] <= 0 and row["in_tokens"] <= 0:
            continue
        if hours and _dt.datetime.fromisoformat(stamps[run_id]) > cutoff:
            continue
        out.append({"run_id": run_id, "at": stamps[run_id], **row})
    return out


def release_stale(store: Store, *, hours: float) -> int:
    """Explicit recovery: net out reservations older than hours (a release line)."""
    released = 0
    with store_lock(store.layout):
        for row in open_reservations(store, hours=hours):
            _append(
                store,
                {
                    "kind": KIND_FINISH,
                    "run_id": row["run_id"],
                    "actor": "release-stale",
                    "calls": row["calls"],
                    "in_tokens": row["in_tokens"],
                },
            )
            released += 1
    return released


def estimated_calls(chars: int, config: Config) -> int:
    """How many requests a backlog of this size needs (plan-only math)."""
    return max(1, math.ceil(chars / config.write.max_distill_input_chars))
