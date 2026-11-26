"""Delivery channels for the pinned-rules block: one render, one block, many surfaces.

A channel says where a harness accepts the block and whether that surface survives compaction. The
bytes are identical across channels; only the wrapper differs, so a rule cannot drift per harness.
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
class Channel:
    harness: str
    surface: str
    preserved: bool  # survives compaction (a real system message)
    refresh: str
    max_bytes: int

    @property
    def degraded(self) -> bool:
        """True when this harness has no preserved surface: the block is a reminder, not a rule."""
        return not self.preserved


@dataclasses.dataclass(frozen=True)
class Delivery:
    harness: str
    digest: str
    wrote: bool
    degraded: bool
    target: str = ""


CHANNELS: dict[str, Channel] = {
    "hermes": Channel(
        harness="hermes",
        surface=SURFACE_SYSTEM_BLOCK,
        preserved=True,
        refresh=REFRESH_PER_TURN,
        max_bytes=8192,
    ),
    "codex": Channel(
        harness="codex",
        surface=SURFACE_INSTRUCTIONS_FILE,
        preserved=True,
        refresh=REFRESH_PER_RUN,
        max_bytes=32768,
    ),
    "muse": Channel(
        harness="muse",
        surface=SURFACE_PROMPT_PREFIX,
        preserved=False,
        refresh=REFRESH_PER_RUN,
        max_bytes=16384,
    ),
}


def for_harness(name: str) -> Channel:
    """The channel a named harness accepts, or a refusal. No default."""
    try:
        return CHANNELS[name]
    except KeyError as error:
        raise KeyError(f"no channel registered for harness: {name}") from error


def digest_of(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


def wrap(channel: Channel, block: str) -> str:
    """The block as this harness receives it. Content never changes, only the envelope."""
    if channel.surface in {SURFACE_SYSTEM_PROMPT_FILE, SURFACE_INSTRUCTIONS_FILE}:
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


def place(channel: Channel, block: str, *, target: pathlib.Path | None = None,
          state_dir: pathlib.Path | None = None) -> Delivery:
    """Write the block for one harness; record the digest we actually delivered."""
    if len(block.encode("utf-8")) > channel.max_bytes:
        raise ValueError(
            f"{channel.harness}: block is {len(block.encode('utf-8'))} bytes, cap "
            f"{channel.max_bytes}"
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
        _record(state_dir, channel.harness, digest)
    return Delivery(
        harness=channel.harness,
        digest=digest,
        wrote=wrote,
        degraded=channel.degraded,
        target=str(target) if target else "",
    )


def _record(state_dir: pathlib.Path, harness: str, digest: str) -> None:
    path = state_dir / DIGEST_FILENAME
    payload: dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        payload = {str(k): str(v) for k, v in dict(raw).items()}
    payload[harness] = digest
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


def deliver(store, harness: str, target: pathlib.Path) -> Delivery:
    """Render the block once and write it to a harness's prompt file. One call per run."""
    from mnemobun.core import pinned as pinned_rules

    channel = for_harness(channel_name(harness))
    block = pinned_rules.render(store)
    if not block:
        return Delivery(
            harness=channel.harness, digest=digest_of(""), wrote=False, degraded=channel.degraded
        )
    return place(channel, block, target=target, state_dir=store.layout.state_dir)



HARNESS_ALIASES = {"muse-code": "muse"}  # a driver name that differs from its channel name


def channel_name(spec_name: str) -> str:
    return HARNESS_ALIASES.get(spec_name, spec_name)


def executor_block(store, spec_name: str) -> str:
    """The block a headless harness needs prepended to its system prompt, or "" when it has none.

    Hermes is skipped: its block rides `system_prompt_block()` inside the agent itself, so
    appending here would deliver the same rules twice.
    """
    from mnemobun.core import pinned as pinned_rules

    try:
        channel = for_harness(channel_name(spec_name))
    except KeyError:
        return ""
    if channel.surface == SURFACE_SYSTEM_BLOCK:
        return ""
    block = pinned_rules.render(store)
    if not block:
        return ""
    return wrap(channel, block)
