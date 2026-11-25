"""Advisory health: append-only events, no lock, never blocks the failure it reports."""

from __future__ import annotations

import json
import pathlib
from typing import Any


def _path(store: Any) -> pathlib.Path:
    return pathlib.Path(store.layout.state_dir) / "events.jsonl"


def note(store: Any, code: str, **context: Any) -> None:
    """Best effort: a health note must never raise into a write path."""
    try:
        path = _path(store)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"code": code, "at": str(store.clock.now()), **context}, sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return


def summary(store: Any, code: str | None = None) -> dict[str, Any]:
    path = _path(store)
    counts: dict[str, int] = {}
    last: dict[str, Any] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            entry = json.loads(raw)
            counts[entry.get("code", "?")] = counts.get(entry.get("code", "?"), 0) + 1
            last = entry
    except OSError:
        return {"counts": {}, "last": {}}
    if code:
        return {"count": counts.get(code, 0), "last": last if last.get("code") == code else {}}
    return {"counts": counts, "last": last}
