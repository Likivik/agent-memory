"""Claude Code dialect."""

from .base import *  # noqa: F403

MEM_TOOL_PATTERN = "Bash(mem:*)"
CLAUDE_NATIVE_TOOLS = "Write,Edit,NotebookEdit,WebSearch,WebFetch,Task"
CLAUDE_STRUCTURED_OUTPUT = "json"
CLAUDE_RESULT_TYPE = "result"
CLAUDE_CACHE_READ = "cache_read_input_tokens"
CLAUDE_OUTPUT = "output_tokens"
CLAUDE_INPUT_FIELDS = ("input_tokens", CLAUDE_CACHE_READ, "cache_creation_input_tokens")
CLAUDE_USAGE_FIELDS = (*CLAUDE_INPUT_FIELDS, CLAUDE_OUTPUT)


class ClaudeCodeDialect(Dialect):
    """Its memory is the Write tool aimed at ~/.claude/projects/<cwd>/memory/."""

    supports_tools = True
    tools_by_default = True

    def tool_command(self, spec, *, system_prompt, instructions_file, server, answer_file):
        configured = {
            "mcpServers": {
                server.name: {"type": "stdio", "command": server.command, "args": list(server.args)}
            }
        }
        allowed = ",".join(f"mcp__{server.name}__{tool}" for tool in server.tools)
        return [
            spec.binary,
            "-p",
            "--model",
            spec.model,
            "--strict-mcp-config",
            "--mcp-config",
            json.dumps(configured),
            "--tools",
            "",
            "--allowedTools",
            allowed,
            "--disallowedTools",
            CLAUDE_NATIVE_TOOLS,
            "--system-prompt-file",
            str(instructions_file),
            "--output-format",
            CLAUDE_STRUCTURED_OUTPUT,
        ]

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
            "-p",
            "--model",
            spec.model,
            "--max-turns",
            str(max_turns),
            "--disallowedTools",
            CLAUDE_NATIVE_TOOLS,
        ]
        if tools_enabled:
            command += ["--allowedTools", tool_pattern]
        else:
            command += ["--tools", "", "--strict-mcp-config"]
        return command + ["--system-prompt", system_prompt or BARE_SYSTEM_PROMPT]

    def answer(self, stdout: str, answer_file: pathlib.Path) -> str:
        text = (_claude_result(stdout) or {}).get("result")
        return text.strip() if isinstance(text, str) else stdout.strip()

    def usage(self, stdout: str) -> HostUsage | None:
        result = _claude_result(stdout) or {}
        reported = result.get("usage")
        if not isinstance(reported, dict):
            return None
        counts = {key: _count(reported.get(key)) for key in CLAUDE_USAGE_FIELDS}
        return HostUsage(
            turns=_count(result.get("num_turns")),
            input_tokens=sum(counts[key] for key in CLAUDE_INPUT_FIELDS),
            cached_input_tokens=counts[CLAUDE_CACHE_READ],
            output_tokens=counts[CLAUDE_OUTPUT],
        )

    def disables_native_memory(self, rendered_command: str) -> bool:
        return CLAUDE_NATIVE_TOOLS in rendered_command


def _claude_result(stdout: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("type") == CLAUDE_RESULT_TYPE:
        return parsed
    return None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _host_usage(stdout: str) -> HostUsage | None:
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
    return HostUsage(turns=turns, **totals)
