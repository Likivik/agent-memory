"""How one harness is spoken to: argv shape, stdin, answer extraction. Pure, so testable offline."""

from __future__ import annotations

import json
import pathlib

from .constants import MEM_TOOL_PATTERN, PROMPT_PLACEHOLDER
from .types import DriverSpec, DriverUsage, ToolServer


class Transport:
    """How one host is spoken to. Every method is pure, so the shape is testable offline."""

    prompt_on_stdin = True
    supports_tools = False
    tools_by_default = False

    def tool_command(
        self,
        spec: DriverSpec,
        *,
        system_prompt: str,
        instructions_file: pathlib.Path,
        server: ToolServer,
        answer_file: pathlib.Path,
    ) -> list[str]:
        raise NotImplementedError

    def command(
        self,
        spec: DriverSpec,
        *,
        tools_enabled: bool,
        system_prompt: str,
        max_turns: int,
        store_root: pathlib.Path | None,
        answer_file: pathlib.Path,
        tool_pattern: str = MEM_TOOL_PATTERN,
        workdir: pathlib.Path | None = None,
    ) -> list[str]:
        raise NotImplementedError

    def stdin(self, prompt: str, system_prompt: str) -> str:
        return prompt

    def answer(self, stdout: str, answer_file: pathlib.Path) -> str:
        return stdout.strip()

    def usage(self, stdout: str) -> DriverUsage | None:
        return _host_usage(stdout)

    def disables_native_memory(self, rendered_command: str) -> bool:
        raise NotImplementedError

    def invocation(
        self,
        command: list[str],
        prompt: str,
        system_prompt: str,
        scratch: pathlib.Path,
    ) -> tuple[list[str], str]:
        payload = self.stdin(prompt, system_prompt)
        if self.prompt_on_stdin:
            return command, payload
        return [payload if part == PROMPT_PLACEHOLDER else part for part in command], ""


def _stream_result(stdout: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("type") == "result":
        return parsed
    return None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _host_usage(stdout: str) -> DriverUsage | None:
    turns = 0
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }
    found = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        turns += 1
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        found = True
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    if not found:
        return None
    return DriverUsage(turns=turns, **totals)
