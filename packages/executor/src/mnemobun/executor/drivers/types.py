"""The shapes a run produces and the spec that drives it."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess


@dataclasses.dataclass(frozen=True)
class DriverResult:
    text: str
    ok: bool
    seconds: float
    error: str = ""
    usage: DriverUsage | None = None
    phases: DriverPhases | None = None


@dataclasses.dataclass(frozen=True)
class DriverUsage:
    turns: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


@dataclasses.dataclass(frozen=True)
class DriverPhases:
    """Observed Codex process phases; together they account for Driver wall time."""

    startup_seconds: float
    model_wait_seconds: float
    mcp_seconds: float
    shutdown_seconds: float


@dataclasses.dataclass(frozen=True)
class ToolServer:
    """A stdio MCP server the host starts for one run, and the only tools it may call."""

    name: str
    command: str
    args: tuple[str, ...]
    tools: tuple[str, ...]
    host_analytics_enabled: bool = True


@dataclasses.dataclass(frozen=True)
class DriverSpec:
    name: str
    binary: str
    model: str = ""  # no model is chosen for you: a host spec must name one
    timeout_seconds: float = 300.0
    attempts: int = 3
    retry_backoff_seconds: float = 5.0
    provider: str = ""
    allow_data_training: bool = False
    reasoning_effort: str = ""

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def version(self) -> str:
        resolved = shutil.which(self.binary)
        if resolved is None:
            return "unavailable"
        try:
            completed = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True, check=False, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        output = (completed.stdout.strip() or completed.stderr.strip()).splitlines()
        return output[0] if completed.returncode == 0 and output else "unknown"

