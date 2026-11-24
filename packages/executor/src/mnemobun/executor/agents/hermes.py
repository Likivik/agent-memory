"""hermes dialect."""

from .base import *  # noqa: F403


class HermesDialect(Dialect):
    """One-shot mode loads its own memory toolset by default; the toolset list drops it."""

    prompt_on_stdin = False
    supports_tools = True
    tools_by_default = True

    def tool_command(self, spec, *, system_prompt, instructions_file, server, answer_file):
        toolset = self.toolset(server)
        command = [
            spec.binary,
            "chat",
            "--oneshot",
            "--query-file",
            PROMPT_PLACEHOLDER,
            "--model",
            self.routed_model(spec),
            "--toolsets",
            toolset,
            "--max-turns",
            str(HERMES_NATIVE_MAX_TURNS),
            "--ignore-rules",
        ]
        if spec.provider:
            command += ["--provider", spec.provider]
        return command

    @staticmethod
    def toolset(server: ToolServer) -> str:
        """Give Write and Manage distinct names without exposing arbitrary profile servers."""
        if server.name == "memory":
            return HERMES_WRITE_SERVER_NAME
        if server.name == "memory_review":
            return HERMES_MANAGE_SERVER_NAME
        return server.name

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
        command = [spec.binary, "-z", PROMPT_PLACEHOLDER, "--model", self.routed_model(spec)]
        if spec.provider:
            command += ["--provider", spec.provider]
        command += ["-t", HERMES_TOOLSETS if tools_enabled else ""]
        if not tools_enabled:
            # extraction profile (2026-11-24 trust ruling): no tools, rules APPLY,
            # nothing to approve. The interactive form keeps --ignore-rules/--yolo.
            return command + ["--yolo"]
        return command + ["--ignore-rules", "--yolo"]

    def routed_model(self, spec: HostSpec) -> str:
        """Hermes eats one `<provider>/` prefix off the model as routing, so a backend that
        wants a publisher-qualified id — Vertex wants `google/<model>` — needs one added back."""
        if spec.provider == "gemini":
            return f"{spec.provider}/{spec.model}"
        return spec.model

    def stdin(self, prompt: str, system_prompt: str) -> str:
        return (system_prompt + PROMPT_SEPARATOR + prompt) if system_prompt else prompt

    def invocation(self, command, prompt, system_prompt, scratch):
        prompt_path = scratch / PROMPT_FILENAME
        prompt_path.write_text(self.stdin(prompt, system_prompt), encoding="utf-8")
        return [str(prompt_path) if part == PROMPT_PLACEHOLDER else part for part in command], ""

    def disables_native_memory(self, rendered_command: str) -> bool:
        marker = "--toolsets " if "--toolsets " in rendered_command else "-t "
        _, _, tail = rendered_command.partition(marker)
        toolsets = tail.split(" ")[0] if tail else ""
        return "memory" not in toolsets.split(",")
