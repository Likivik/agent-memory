"""muse dialect."""

import os

from .base import *  # noqa: F403


class MuseCodeDialect(Dialect):
    """Muse's headless transport: JSONL out, prompt file in, sandbox kept on."""

    supports_tools = True
    tools_by_default = True

    def tool_command(self, spec, *, system_prompt, instructions_file, server, answer_file):
        selected = [f"mcp__{server.name}__{tool}" for tool in server.tools]
        command = [
            spec.binary,
            "exec",
            "-c",
            f"{MUSE_TOOLSET_SETTING}={json.dumps(selected)}",
            "--json",
            "--no-foreign-personal-context",
            "--disable-reminders",
            "--no-session-log",
            "--disable-shell",
            "--disable-web-tools",
            "--disable-write",
            "--approval-mode",
            "never",
            "--max-model-steps",
            str(MUSE_NATIVE_MAX_MODEL_STEPS),
            "--prompt-file",
            PROMPT_PLACEHOLDER,
            "--workspace",
            str(answer_file.parent.resolve()),
        ]
        if spec.model:
            command += ["--model", spec.model]
        if spec.reasoning_effort:
            command += ["--reasoning-effort", spec.reasoning_effort]
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
        workspace = self._workspace(tools_enabled, store_root, workdir, answer_file.parent)
        command = [
            spec.binary,
            "exec",
            "--json",
            "--no-foreign-personal-context",
            "--disable-reminders",
            "--prompt-file",
            PROMPT_PLACEHOLDER,
            "--max-model-steps",
            str(max_turns),
            "--workspace",
            str(workspace),
        ]
        if not tools_enabled:
            command += [
                "--disable-shell",
                "--disable-web-tools",
                "--approval-mode",
                "never",
            ]
        if spec.model:
            command += ["--model", spec.model]
        if spec.reasoning_effort:
            command += ["--reasoning-effort", spec.reasoning_effort]
        return command

    def stdin(self, prompt: str, system_prompt: str) -> str:
        return (system_prompt + PROMPT_SEPARATOR + prompt) if system_prompt else prompt

    def invocation(self, command, prompt, system_prompt, scratch):
        prompt_path = scratch / PROMPT_FILENAME
        prompt_path.write_text(self.stdin(prompt, system_prompt), encoding="utf-8")
        return [str(prompt_path) if part == PROMPT_PLACEHOLDER else part for part in command], ""

    def answer(self, stdout: str, answer_file: pathlib.Path) -> str:
        answer = ""
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            candidates = [event]
            payload = event.get("payload")
            if isinstance(payload, dict):
                candidates.append(payload)
                nested = payload.get("event")
                if isinstance(nested, dict):
                    candidates.append(nested)
            for candidate in candidates:
                kind = candidate.get("kind")
                text = candidate.get("text")
                if kind in ("run_terminal", "assistant_message", "final_answer") and isinstance(
                    text, str
                ):
                    answer = text.strip()
        return answer

    def disables_native_memory(self, rendered_command: str) -> bool:
        return all(
            flag in rendered_command for flag in ("--workspace", "--no-foreign-personal-context")
        )

    @staticmethod
    def _workspace(tools_enabled, store_root, workdir, scratch):
        if not tools_enabled or store_root is None:
            workspace = (workdir or scratch).resolve()
            MuseCodeDialect._require_no_native_memory(workspace)
            return workspace
        roots = [store_root.resolve(), (workdir or scratch).resolve()]
        common = pathlib.Path(os.path.commonpath([str(path) for path in roots]))
        unsafe = {pathlib.Path("/"), pathlib.Path.home().resolve()}
        if common in unsafe:
            raise ValueError(
                "Muse sandbox needs the experiment store and workdir under one safe workspace"
            )
        MuseCodeDialect._require_no_native_memory(common)
        return common

    @staticmethod
    def _require_no_native_memory(workspace: pathlib.Path) -> None:
        if (workspace / ".agents" / "memory").exists():
            raise ValueError("Muse experiment workspace contains native .agents/memory")
