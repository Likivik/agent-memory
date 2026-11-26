"""How one harness is spoken to: argv shape, stdin, answer extraction. Pure, so testable offline."""

from __future__ import annotations

import pathlib

from .constants import MEM_TOOL_PATTERN, PROMPT_PLACEHOLDER
from .helpers import _host_usage
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

