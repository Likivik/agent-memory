"""Codex CLI: prompt on argv, answer in its last message."""

import json
import pathlib

from .constants import (
    CODEX_DISABLED_FEATURES,
    CODEX_SANDBOX_READONLY,
    CODEX_SANDBOX_TOOLS,
    CODEX_TOOL_APPROVAL,
    MEM_TOOL_PATTERN,
    PROMPT_SEPARATOR,
)
from .transport import Transport


class CodexTransport(Transport):
    """No system-prompt flag, so it rides in the prompt; and stdout carries the whole session
    transcript, so the final message is read from the file the host writes it to."""


    supports_tools = True
    tools_by_default = True

    def tool_command(self, spec, *, system_prompt, instructions_file, server, answer_file):
        prefix = f"mcp_servers.{server.name}"
        overrides = {
            "model_instructions_file": str(instructions_file),
            f"{prefix}.command": server.command,
            f"{prefix}.args": list(server.args),
            f"{prefix}.required": True,
            f"{prefix}.enabled_tools": list(server.tools),
            f"{prefix}.default_tools_approval_mode": CODEX_TOOL_APPROVAL,
        }
        if not server.host_analytics_enabled:
            # A bounded machine-consumed review has no use for delaying process shutdown on
            # Codex's synchronous analytics flush. This does not alter the agent turn or MCP.
            overrides["analytics.enabled"] = False
        command = [
            spec.binary,
            "exec",
            "--model",
            spec.model,
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            CODEX_SANDBOX_READONLY,
            "--output-last-message",
            str(answer_file),
        ]
        for key, value in overrides.items():
            command += ["-c", f"{key}={json.dumps(value)}"]
        for feature in CODEX_DISABLED_FEATURES:
            command += ["--disable", feature]
        return command

    def command(
        self,
        spec,
        *,
        tools_enabled,
        system_prompt,
        max_turns,
        store_root,
        answer_file,
        tool_pattern=MEM_TOOL_PATTERN,
        workdir=None,
    ):
        command = [
            spec.binary,
            "exec",
            "--model",
            spec.model,
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-last-message",
            str(answer_file),
        ]
        if tools_enabled:
            command += ["--sandbox", CODEX_SANDBOX_TOOLS]
            if store_root is not None:
                command += ["--add-dir", str(store_root)]
            return command
        return command + ["--sandbox", CODEX_SANDBOX_READONLY]

    def stdin(self, prompt: str, system_prompt: str) -> str:
        return (system_prompt + PROMPT_SEPARATOR + prompt) if system_prompt else prompt

    def answer(self, stdout: str, answer_file: pathlib.Path) -> str:
        if answer_file.exists():
            written = answer_file.read_text(encoding="utf-8").strip()
            if written:
                return written
        return ""

    def disables_native_memory(self, rendered_command: str) -> bool:
        return "--ignore-user-config" in rendered_command
