"""Pure domain values for a write: what to record, under which key, to which route.

Nothing here touches the filesystem, the clock or the host. Adapters translate into these.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

KEY_LENGTH = 12
SEPARATOR = "\x1f"


@dataclasses.dataclass(frozen=True)
class DedupeKey:
    """Effectively-once identity for a captured turn."""

    value: str

    @classmethod
    def of(cls, session_id: str, user: str, assistant: str, *, day: str = "") -> DedupeKey:
        material = SEPARATOR.join((session_id or day or "anon", user, assistant))
        return cls(hashlib.sha256(material.encode("utf-8")).hexdigest()[:KEY_LENGTH])


@dataclasses.dataclass(frozen=True)
class RecordSpec:
    """A typed write. `refuse_if_exists` turns a collision into a refusal, not a rename."""

    abstract: str
    type: str
    body: str = ""
    name: str = ""
    fields: dict[str, Any] = dataclasses.field(default_factory=dict)
    provenance: tuple[str, ...] = ()
    refuse_if_exists: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"abstract": self.abstract, "type": self.type}
        if self.body:
            payload["body"] = self.body
        if self.name:
            payload["name"] = self.name
        if self.fields:
            payload["fields"] = dict(self.fields)
        if self.provenance:
            payload["provenance"] = list(self.provenance)
        if self.refuse_if_exists:
            payload["refuse_if_exists"] = True
        return payload


@dataclasses.dataclass(frozen=True)
class Route:
    """One model identity: a provider slug plus a model id. A bare id is truncated."""

    provider: str = ""
    model: str = ""

    @property
    def is_set(self) -> bool:
        return bool(self.provider and self.model)

    def label(self) -> str:
        return f"{self.provider} \u00b7 {self.model}" if self.is_set else ""


STATE_RESOLVED = "resolved"
STATE_UNSET = "unset"
STATE_UNAVAILABLE = "unavailable"
STATE_VANISHED = "vanished"


@dataclasses.dataclass(frozen=True)
class RouteState:
    state: str
    route: Route
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.state == STATE_RESOLVED
