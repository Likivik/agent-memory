"""Turn capture: the one place raw turn text becomes a record."""

from __future__ import annotations

from typing import Any

from mnemobun.core import health
from mnemobun.core.slug import Slug
from mnemobun.core.specs import DedupeKey, RecordSpec

PROVENANCE_TURN = "turn"


class TurnCaptureService:
    """Append the raw turn, keyed by a stable digest so a replay is refused, not renamed."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def capture(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> dict[str, Any]:
        user = user_content.strip()
        assistant = assistant_content.strip()
        if not user and not assistant:
            return {"written": "", "skipped": "empty"}
        limit = self.store.config.storage.slug_max_length
        day = self.store.clock.now().strftime("%Y-%m-%d")
        key = DedupeKey.of(session_id, user, assistant, day=day)
        name = Slug.of(f"turn-{key.value}", limit, identity=True).value
        spec = RecordSpec(
            abstract=user[: self.store.config.storage.abstract_max_chars],
            type="event",
            body=f"USER: {user}\nASSISTANT: {assistant}",
            name=name,
            provenance=(PROVENANCE_TURN,),
            refuse_if_exists=True,
        )
        try:
            record = self.store.record(**spec.as_dict())
        except Exception as error:  # never raise into the host: memory is best effort
            detail = str(error)[:200]
            code = "dedupe_refused" if "already recorded" in detail else "capture_failed"
            health.note(self.store, code, detail=detail, key=key.value)
            return {"written": "", "skipped": code, "error": detail}
        return {"written": getattr(record, "name", ""), "skipped": ""}
