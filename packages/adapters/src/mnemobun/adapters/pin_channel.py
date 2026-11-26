"""Delivery channels for the pinned-rules block: one render, many transports.

A channel says where a host accepts the block and whether that surface survives compaction. The
bytes are identical across channels; only the wrapper differs, so a rule cannot drift per host.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib

SURFACE_SYSTEM_BLOCK = "system_block"
SURFACE_SYSTEM_PROMPT_FILE = "system_prompt_file"
SURFACE_INSTRUCTIONS_FILE = "instructions_file"
SURFACE_PROMPT_PREFIX = "prompt_prefix"

REFRESH_PER_TURN = "per_turn"
REFRESH_PER_RUN = "per_run"

MARKER_START = "<!-- mnemobun:pinned:start -->"
MARKER_END = "<!-- mnemobun:pinned:end -->"
DIGEST_FILENAME = "pin-digest.json"


@dataclasses.dataclass(frozen=True)
class PinChannel:
    host: str
    surface: str
    preserved: bool  # survives compaction (a real system message)
    refresh: str
    max_bytes: int

    @property
    def degraded(self) -> bool:
        """True when this host has no preserved surface: the block is a reminder, not a rule."""
        return not self.preserved


@dataclasses.dataclass(frozen=True)
class Delivery:
    host: str
    digest: str
    wrote: bool
    degraded: bool
    target: str = ""


REGISTRY: dict[str, PinChannel] = {
    "hermes": PinChannel(
        host="hermes",
        surface=SURFACE_SYSTEM_BLOCK,
        preserved=True,
        refresh=REFRESH_PER_TURN,
        max_bytes=8192,
    ),
    "codex": PinChannel(
        host="codex",
        surface=SURFACE_INSTRUCTIONS_FILE,
        preserved=True,
        refresh=REFRESH_PER_RUN,
        max_bytes=32768,
    ),
    "muse": PinChannel(
        host="muse",
        surface=SURFACE_PROMPT_PREFIX,
        preserved=False,
        refresh=REFRESH_PER_RUN,
        max_bytes=16384,
    ),
}


def channel(host: str) -> PinChannel:
    try:
        return REGISTRY[host]
    except KeyError as error:
        raise KeyError(f"unknown pin channel: {host}") from error


def digest_of(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


def wrap(channel_: PinChannel, block: str) -> str:
    """The block as this host receives it. Content never changes, only the envelope."""
    if channel_.surface in {SURFACE_SYSTEM_PROMPT_FILE, SURFACE_INSTRUCTIONS_FILE}:
        return f"{MARKER_START}\n{block}\n{MARKER_END}"
    return block


def splice(existing: str, block: str) -> str:
    """Replace only our delimited region, leaving every other byte untouched."""
    wrapped = f"{MARKER_START}\n{block}\n{MARKER_END}"
    start = existing.find(MARKER_START)
    end = existing.find(MARKER_END)
    if start >= 0 and end >= 0 and end < start:
        start = end = -1  # reversed markers: treat the file as having no region
    if start < 0 or end < 0:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        return f"{existing}{separator}{wrapped}\n"
    return f"{existing[:start]}{wrapped}{existing[end + len(MARKER_END):]}"


def deliver(channel_: PinChannel, block: str, *, target: pathlib.Path | None = None,
            state_dir: pathlib.Path | None = None) -> Delivery:
    """Place the block for one host; record the digest we actually delivered."""
    if len(block.encode("utf-8")) > channel_.max_bytes:
        raise ValueError(
            f"{channel_.host}: block is {len(block.encode('utf-8'))} bytes, cap "
            f"{channel_.max_bytes}"
        )
    digest = digest_of(block)
    wrote = False
    if target is not None:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = splice(current, block)
        if updated != current:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
            wrote = True
    if state_dir is not None:
        _record(state_dir, channel_.host, digest)
    return Delivery(
        host=channel_.host,
        digest=digest,
        wrote=wrote,
        degraded=channel_.degraded,
        target=str(target) if target else "",
    )


def _record(state_dir: pathlib.Path, host: str, digest: str) -> None:
    path = state_dir / DIGEST_FILENAME
    payload: dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        payload = {str(k): str(v) for k, v in dict(raw).items()}
    payload[host] = digest
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recorded(state_dir: pathlib.Path) -> dict[str, str]:
    path = state_dir / DIGEST_FILENAME
    if not path.exists():
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except ValueError:
        return {}


def sync(store, host: str, target: pathlib.Path) -> Delivery:
    """Render the block and deliver it to a host's prompt file. One call per host per run."""
    from mnemobun.core import pinned as pinned_rules

    channel_ = channel(host)
    block = pinned_rules.render(store)
    if not block:
        return Delivery(host=host, digest=digest_of(""), wrote=False, degraded=channel_.degraded)
    return deliver(channel_, block, target=target, state_dir=store.layout.state_dir)


HARNESS_ALIASES = {"muse-code": "muse"}


def host_name(spec_name: str) -> str:
    return HARNESS_ALIASES.get(spec_name, spec_name)


def executor_block(store, spec_name: str) -> str:
    """The block a headless host needs prepended to its system prompt, or "" when it has none.

    Hermes is skipped: its block rides `system_prompt_block()` inside the host itself, so
    appending here would deliver the same rules twice.
    """
    from mnemobun.core import pinned as pinned_rules

    try:
        channel_ = channel(host_name(spec_name))
    except KeyError:
        return ""
    if channel_.surface == SURFACE_SYSTEM_BLOCK:
        return ""
    block = pinned_rules.render(store)
    if not block:
        return ""
    return wrap(channel_, block)
