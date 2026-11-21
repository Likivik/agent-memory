"""Hermes state.db as a replay source (P9.3, decision D7).

Yields turns — user+assistant pairs — in global chronological order (D8: one
record per turn, no per-message records). Tool messages, session_meta and
compacted/inactive rows are skipped. The schema probe raises a clear error
instead of guessing at drift.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import sqlite3
from collections.abc import Iterator
from pathlib import Path

REQUIRED_COLUMNS = frozenset({"session_id", "role", "content", "timestamp"})
TURN_ROLES = ("user", "assistant")


@dataclasses.dataclass(frozen=True)
class Turn:
    session_id: str
    user: str
    assistant: str
    at: str  # ISO-8601 UTC instant of the user message


def _to_iso(epoch: str | float) -> str:
    moment = dt.datetime.fromtimestamp(float(epoch), tz=dt.UTC)
    return moment.isoformat(timespec="microseconds")


class HermesSource:
    """The messages table of a Hermes state.db, replayed as turns."""

    def __init__(self, state_db_path: str | Path):
        self._path = Path(state_db_path)
        if not self._path.exists():
            raise RuntimeError(f"state.db not found: {self._path}")
        with sqlite3.connect(f"file:{self._path}?mode=ro", uri=True) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise RuntimeError(
                f"state.db schema drift: messages is missing {sorted(missing)}; "
                "the adapter must be updated before import"
            )

    def turns(self) -> Iterator[Turn]:
        connection = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT session_id, role, content, timestamp FROM messages "
                "WHERE role IN ('user', 'assistant') AND active = 1 AND compacted = 0 "
                "AND content IS NOT NULL AND trim(content) != '' "
                "ORDER BY cast(timestamp as real), id"
            ).fetchall()
        finally:
            connection.close()
        open_user: tuple[str, str, str] | None = None  # (session, content, at)
        for row in rows:
            role = str(row["role"])
            content = str(row["content"]).strip()
            session = str(row["session_id"])
            at = _to_iso(row["timestamp"])
            if role == "user":
                if open_user is not None:
                    yield Turn(
                        session_id=open_user[0], user=open_user[1], assistant="", at=open_user[2]
                    )
                open_user = (session, content, at)
            else:
                if open_user is not None and open_user[0] == session:
                    yield Turn(
                        session_id=open_user[0],
                        user=open_user[1],
                        assistant=content,
                        at=open_user[2],
                    )
                    open_user = None
                # an assistant message without an open user turn starts nothing (D8)
        if open_user is not None:
            yield Turn(session_id=open_user[0], user=open_user[1], assistant="", at=open_user[2])
