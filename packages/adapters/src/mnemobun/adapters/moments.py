"""Three universal moments and each harness's event names."""

from __future__ import annotations

MOMENT_INJECT = "inject"
MOMENT_PAUSE = "pause"
MOMENT_EVICT = "evict"

HARNESS_CODEX = "codex"
HARNESS_MUSE_CODE = "muse-code"
HARNESS_HERMES = "hermes"
HARNESS_GENERIC = "generic"

MOMENTS: dict[str, dict[str, str]] = {
    HARNESS_CODEX: {
        "SessionStart": MOMENT_INJECT,
        "Stop": MOMENT_PAUSE,
        "PreCompact": MOMENT_EVICT,
    },
    HARNESS_MUSE_CODE: {
        "SessionStart": MOMENT_INJECT,
        "Stop": MOMENT_PAUSE,
        "SessionEnd": MOMENT_PAUSE,
        "PreCompact": MOMENT_EVICT,
    },
    HARNESS_HERMES: {
        "SessionStart": MOMENT_INJECT,
        "Stop": MOMENT_PAUSE,
        "SessionEnd": MOMENT_PAUSE,
        "PreCompact": MOMENT_EVICT,
    },
    HARNESS_GENERIC: {
        MOMENT_INJECT: MOMENT_INJECT,
        MOMENT_PAUSE: MOMENT_PAUSE,
        MOMENT_EVICT: MOMENT_EVICT,
    },
}


def moment_for(host: str, event: str) -> str | None:
    return MOMENTS.get(host, {}).get(event)


def hosts() -> tuple[str, ...]:
    return tuple(MOMENTS)
