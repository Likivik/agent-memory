"""The MCP tools. Each one collapses onto the same core call the CLI makes.

The tool-surface mapping onto the design-doc names lives in docs/ (single
source of truth); this module owns the catalogue and dispatch only.
"""

from __future__ import annotations

from mnemobun.core import timestamp
from mnemobun.core.errors import FieldError, ValidationError
from mnemobun.core.recall import Recall
from mnemobun.core.store import LEVEL_FULL, LEVELS, Store

TOOL_RECALL = "memory_recall"
TOOL_READ = "memory_read"
TOOL_RECORD = "memory_record"
TOOL_CORRECT = "memory_correct"
TOOL_SUPERSEDE = "memory_supersede"
TOOL_DELETE = "memory_delete"
TOOL_TRACE = "memory_trace"
TOOL_MERGE = "memory_merge"
TOOL_FEEDBACK = "memory_feedback"
TOOL_TIMELINE = "memory_timeline"
TOOL_VERIFY = "memory_verify"
TOOL_STATS = "memory_stats"
TOOL_FORGET_SESSION = "memory_forget_session"


SCHEMAS: dict[str, dict[str, object]] = {
    TOOL_RECALL: {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "scope": {"type": "string"},
            "as_of": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["query"],
    },
    TOOL_READ: {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "level": {"type": "string", "enum": list(LEVELS)},
        },
        "required": ["name"],
    },
    TOOL_RECORD: {
        "type": "object",
        "properties": {
            "abstract": {"type": "string"},
            "type": {"type": "string"},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}},
            "body": {"type": "string"},
            "name": {"type": "string"},
            "create_group": {"type": "boolean"},
            "links": {"type": "array", "items": {"type": "string"}},
            "conflicts": {"type": "array", "items": {"type": "string"}},
            "provenance": {"type": "array", "items": {"type": "string"}},
            "supersedes": {"type": "string"},
        },
        "required": ["abstract", "type"],
    },
    TOOL_CORRECT: {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "abstract": {"type": "string"},
            "body": {"type": "string"},
            "supersede_with": {"type": "string"},
            "links": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Replace all links; empty list removes all links",
            },
            "provenance": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    },
    TOOL_SUPERSEDE: {
        "type": "object",
        "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
        "required": ["old", "new"],
    },
    TOOL_DELETE: {
        "type": "object", "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    TOOL_TRACE: {
        "type": "object",
        "properties": {"name": {"type": "string"}, "pointer": {"type": "string"}},
        "required": ["name"],
    },
    TOOL_MERGE: {
        "type": "object",
        "properties": {
            "names": {"type": "array", "items": {"type": "string"}},
            "name": {"type": "string"},
            "abstract": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["names", "abstract", "body"],
    },
    TOOL_FEEDBACK: {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "direction": {"type": "string", "enum": ["boost", "penalize"]},
        },
        "required": ["name", "direction"],
    },
    TOOL_TIMELINE: {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    TOOL_VERIFY: {
        "type": "object",
        "properties": {"draft": {"type": "string"}, "query": {"type": "string"}},
        "required": ["draft", "query"],
    },
    TOOL_STATS: {"type": "object", "properties": {}},
    TOOL_FORGET_SESSION: {
        "type": "object",
        "properties": {"session": {"type": "string"}},
        "required": ["session"],
    },
}

DESCRIPTIONS = {
    TOOL_RECALL: "Search the memory store and return an L0 list of candidates.",
    TOOL_READ: "Read one memory at a chosen level of detail.",
    TOOL_RECORD: "Write one memory into the store.",
    TOOL_CORRECT: "Update a memory in place, or supersede it with a newer one.",
    TOOL_SUPERSEDE: "End an old memory's validity in favor of an existing active memory.",
    TOOL_DELETE: "End a named memory's validity while retaining historical evidence.",
    TOOL_TRACE: "Read only the archived messages cited by a named memory.",
    TOOL_MERGE: "Combine named active memories atomically and retain their history.",
    TOOL_FEEDBACK: "Raise or lower a memory's weight explicitly.",
    TOOL_TIMELINE: (
        "Show a claim's proof tree: antecedents, conflicts, provenance, standing history."
    ),
    TOOL_VERIFY: (
        "Audit a drafted answer against memory: supported, conflicting, unsupported,"
        " or abstain."
    ),
    TOOL_STATS: "Store health: counts by type and standing, index size, last sync.",
    TOOL_FORGET_SESSION: (
        "Forget everything a session produced: ends validity, retracts standing"
        " permanently, propagates to dependents."
    ),
}


def catalogue() -> list[dict[str, object]]:
    return [
        {"name": name, "description": DESCRIPTIONS[name], "inputSchema": SCHEMAS[name]}
        for name in SCHEMAS
    ]


def dispatch(store: Store, tool: str, arguments: dict[str, object]) -> dict[str, object]:
    if tool not in SCHEMAS:
        raise ValidationError([FieldError("tool", f"unknown tool: {tool}")])
    _require(tool, arguments)
    handler = _HANDLERS[tool]
    return handler(store, arguments)


def _require(tool: str, arguments: dict[str, object]) -> None:
    if "links" in arguments and (
        not isinstance(arguments["links"], list)
        or not all(isinstance(item, str) for item in arguments["links"])
    ):
        raise ValidationError([FieldError("links", "must be an array of memory names")])
    if "names" in arguments and (
        not isinstance(arguments["names"], list)
        or not all(isinstance(item, str) for item in arguments["names"])
    ):
        raise ValidationError([FieldError("names", "must be an array of memory names")])
    if "provenance" in arguments and (
        not isinstance(arguments["provenance"], list)
        or not all(isinstance(item, str) for item in arguments["provenance"])
    ):
        raise ValidationError([FieldError("provenance", "must be an array of references")])
    schema = SCHEMAS[tool]
    properties = schema.get("properties")
    for field, value in arguments.items():
        rules = properties.get(field) if isinstance(properties, dict) else None
        if not isinstance(rules, dict):
            continue
        kind = rules.get("type")
        valid = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }.get(str(kind), True)
        if not valid:
            raise ValidationError([FieldError(field, f"must be a {kind}")])
        if (
            isinstance(value, dict)
            and rules.get("additionalProperties") == {"type": "string"}
            and not all(
                isinstance(key, str) and isinstance(item, str) for key, item in value.items()
            )
        ):
            raise ValidationError([FieldError(field, "must map strings to strings")])
        minimum = rules.get("minimum")
        if isinstance(minimum, int) and isinstance(value, int) and value < minimum:
            raise ValidationError([FieldError(field, f"must be at least {minimum}")])
    required = schema.get("required")
    missing = [
        field
        for field in (required if isinstance(required, list) else [])
        if not str(arguments.get(field, "")).strip()
    ]
    if missing:
        raise ValidationError([FieldError(field, "required") for field in missing])
    properties = schema.get("properties")
    unknown = set(arguments) - set(properties if isinstance(properties, dict) else {})
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValidationError([FieldError("arguments", f"unknown field: {names}")])
    for field, rules in (properties if isinstance(properties, dict) else {}).items():
        allowed = rules.get("enum") if isinstance(rules, dict) else None
        value = arguments.get(field)
        if allowed and value is not None and value not in allowed:
            raise ValidationError([FieldError(field, f"must be one of {', '.join(allowed)}")])


def _recall(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    as_of = _optional(arguments, "as_of")
    if as_of is not None and not timestamp.is_valid(as_of):
        raise ValidationError(
            [FieldError("as_of", "must be an ISO-8601 date or a date-time with a time zone")]
        )
    hits = Recall(store).recall(
        str(arguments["query"]),
        scope=_optional(arguments, "scope"),
        as_of=as_of,
        limit=int(str(arguments["limit"])) if arguments.get("limit") else None,
    )
    return {
        "query": str(arguments["query"]),
        "recall_fingerprint": store.config.recall_fingerprint(),
        "hits": [hit.as_dict() for hit in hits],
    }


def _read(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    result = store.read(str(arguments["name"]), level=str(arguments.get("level") or LEVEL_FULL))
    return {
        "name": result.record.name,
        "level": result.level,
        "abstract": result.record.abstract,
        "path": str(result.record.path),
        "outline": list(result.outline),
        "text": result.text,
        "provenance": list(result.record.provenance),
    }


def _record(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    written = store.record(
        abstract=str(arguments["abstract"]),
        type=str(arguments["type"]),
        fields=_string_map(arguments.get("fields")),
        body=str(arguments.get("body") or ""),
        name=_optional(arguments, "name"),
        create_group=bool(arguments.get("create_group")),
        links=_string_list(arguments.get("links")),
        provenance=_string_list(arguments.get("provenance")),
        supersedes=_optional(arguments, "supersedes"),
    )
    # Decision 3: conflicts are agent-declared, never auto-detected.
    for peer in _string_list(arguments.get("conflicts")):
        from mnemobun.core import standing

        standing.add_conflict(store, written.name, peer)
    return {"name": written.name, "path": str(written.path), "updated": written.updated}


def _correct(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    corrected = store.correct(
        str(arguments["name"]),
        abstract=_optional(arguments, "abstract"),
        body=_optional(arguments, "body"),
        supersede_with=_optional(arguments, "supersede_with"),
        links=_string_list(arguments["links"]) if "links" in arguments else None,
        provenance=_string_list(arguments["provenance"]) if "provenance" in arguments else None,
    )
    return {
        "name": corrected.name,
        "superseded_by": corrected.superseded_by,
        "updated": corrected.updated,
    }


def _feedback(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    step = store.config.weight.boost_step
    delta = step if arguments["direction"] == "boost" else -step
    updated = store.feedback(str(arguments["name"]), delta)
    return {"name": updated.name, "weight": updated.weight}


def _supersede(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    replaced = store.supersede(str(arguments["old"]), str(arguments["new"]))
    return {"name": replaced.name, "superseded_by": replaced.superseded_by,
            "invalid_at": replaced.invalid_at}


def _delete(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    removed = store.delete(str(arguments["name"]))
    return {"name": removed.name, "status": removed.status, "invalid_at": removed.invalid_at}


def _trace(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    return store.trace_evidence(str(arguments["name"]), _optional(arguments, "pointer")).as_dict()


def _merge(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    merged = store.merge(
        _string_list(arguments["names"]), str(arguments["abstract"]),
        str(arguments["body"]), name=_optional(arguments, "name"),
    )
    return {"name": merged.name, "path": str(merged.path),
            "sources": _string_list(arguments["names"])}


def _optional(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    return str(value) if value is not None and str(value) != "" else None


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _stats(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    import pathlib

    from mnemobun.core.database import Database

    by_type: dict[str, int] = {}
    by_standing: dict[str, int] = {}
    records = store.records(include_invalid=True)
    for record in records:
        by_type[record.type] = by_type.get(record.type, 0) + 1
        by_standing[record.standing] = by_standing.get(record.standing, 0) + 1
    index_db = pathlib.Path(store.layout.index_db)
    with Database(store.layout).connect() as connection:
        row = connection.execute("SELECT MAX(indexed_at) AS last FROM files").fetchone()
    return {
        "records": len(records),
        "by_type": by_type,
        "by_standing": by_standing,
        "index_bytes": index_db.stat().st_size if index_db.exists() else 0,
        "last_sync": row["last"] if row else None,
    }


def _forget_session(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    from mnemobun.core import standing

    return standing.forget_session(store, str(arguments["session"]))


def _timeline(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    from mnemobun.core import standing

    return standing.timeline(store, str(arguments["name"]))


def _verify(store: Store, arguments: dict[str, object]) -> dict[str, object]:
    from mnemobun.core import audit

    # The MCP surface retrieves evidence deterministically; the label arrives via the
    # host reasoner binding (P3/P6). Without one wired, the honest verdict is abstain.
    return audit.verify(
        store, str(arguments["draft"]), str(arguments["query"]), labeler=None
    )


_HANDLERS = {
    TOOL_RECALL: _recall,
    TOOL_READ: _read,
    TOOL_RECORD: _record,
    TOOL_CORRECT: _correct,
    TOOL_SUPERSEDE: _supersede,
    TOOL_DELETE: _delete,
    TOOL_TRACE: _trace,
    TOOL_MERGE: _merge,
    TOOL_FEEDBACK: _feedback,
    TOOL_TIMELINE: _timeline,
    TOOL_VERIFY: _verify,
    TOOL_STATS: _stats,
    TOOL_FORGET_SESSION: _forget_session,
}
