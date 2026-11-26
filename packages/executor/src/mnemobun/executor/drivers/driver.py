"""One run of one harness: the process, its timeouts, its retries, its error mapping."""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable

from mnemobun.core import observation
from mnemobun.core.config import MUSE_SETTINGS_ENV_VAR

from .. import muse_namespaces
from ..credentials import VertexCredentials
from .constants import (
    ANSWER_FILENAME,
    ERROR_EXCERPT,
    HARNESS_CODEX,
    HARNESS_HERMES,
    HARNESS_MUSE_CODE,
    HERMES_NATIVE_TOOL_REQUIREMENT,
    INSTRUCTIONS_FILENAME,
    LOGGER,
    MEM_TOOL_PATTERN,
    MUSE_NATIVE_TOOL_REQUIREMENT,
    MUSE_RUNTIME_TMPDIR,
    MUSE_TOOLSET_SETTING,
)
from .helpers import _copy_credentials, _merge_provider_settings, _run_codex_jsonl
from .types import DriverResult, DriverSpec, ToolServer


class Driver:
    def __init__(self, spec: DriverSpec):
        self.spec = spec
        from . import TRANSPORTS  # package-level map; resolves after every transport module loads

        transport = TRANSPORTS.get(spec.name)
        if transport is None:
            raise ValueError(f"no transport registered for harness: {spec.name}")
        self.transport = transport
        self.credentials = (
            VertexCredentials()
            if spec.name == HARNESS_HERMES and spec.provider in ("", "gemini")
            else None
        )

    @property
    def name(self) -> str:
        return self.spec.name

    def run(
        self,
        prompt: str,
        store_root: pathlib.Path | None = None,
        tools_enabled: bool = False,
        system_prompt: str = "",
        max_turns: int = 8,
        workdir: pathlib.Path | None = None,
        environment: dict[str, str] | None = None,
        tool_pattern: str = MEM_TOOL_PATTERN,
    ) -> DriverResult:
        return self._retrying(
            lambda: self._attempt(
                prompt,
                store_root,
                tools_enabled,
                system_prompt,
                max_turns,
                workdir,
                environment or {},
                tool_pattern,
            )
        )

    def converse(
        self,
        prompt: str,
        *,
        system_prompt: str,
        server: ToolServer,
        environment: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> DriverResult:
        """One headless run in which the host's own loop calls only the server's tools."""
        return self._retrying(
            lambda: self._converse_attempt(
                # no store root on the converse path: pinned rules ride the tool path (_attempt)
                prompt, system_prompt, server, environment or {}, timeout_seconds, None
            )
        )

    def _retrying(self, attempt: Callable[[], DriverResult]) -> DriverResult:
        last = DriverResult(text="", ok=False, seconds=0.0, error="not attempted")
        for number in range(self.spec.attempts):
            last = attempt()
            if last.ok or last.error in (
                MUSE_NATIVE_TOOL_REQUIREMENT,
                HERMES_NATIVE_TOOL_REQUIREMENT,
            ):
                return last
            if number + 1 < self.spec.attempts:
                time.sleep(self.spec.retry_backoff_seconds * (number + 1))
        return last

    def _converse_attempt(
        self,
        prompt: str,
        system_prompt: str,
        server: ToolServer,
        environment: dict[str, str],
        timeout_seconds: float | None,
        store_root: pathlib.Path | None = None,
    ) -> DriverResult:
        system_prompt = self._with_pins(system_prompt, store_root)
        with tempfile.TemporaryDirectory() as scratch:
            scratch_path = pathlib.Path(scratch)
            answer_file = scratch_path / ANSWER_FILENAME
            instructions_file = scratch_path / INSTRUCTIONS_FILENAME
            instructions_file.write_text(system_prompt, encoding="utf-8")
            command = self.transport.tool_command(
                self.spec,
                system_prompt=system_prompt,
                instructions_file=instructions_file,
                server=server,
                answer_file=answer_file,
            )
            settings = None
            if self.spec.name == HARNESS_HERMES:
                command, prompt = self.transport.invocation(
                    command, prompt, system_prompt, scratch_path
                )
            elif self.spec.name == HARNESS_MUSE_CODE:
                environment = self._isolated_muse_environment(environment, scratch_path)
                # Muse 1.4.9 rejects its process-lifetime tool-output root when TMPDIR and the
                # workspace share the /tmp tree. Muse creates and cleans its own unique child.
                environment["TMPDIR"] = MUSE_RUNTIME_TMPDIR
                self._stage_muse_tool_server(environment, server)
                settings = pathlib.Path(environment["XDG_CONFIG_HOME"]) / "muse" / "settings.json"
                command, prompt = self.transport.invocation(
                    command, prompt, system_prompt, scratch_path
                )

            def invoke() -> DriverResult:
                return self._invoke(
                    command,
                    prompt,
                    self._environment(None, environment),
                    scratch_path,
                    answer_file,
                    require_answer=False,
                    timeout_seconds=timeout_seconds,
                )

            if settings is not None:
                with muse_namespaces.for_muse_settings(settings):
                    return invoke()
            if self.spec.name == HARNESS_HERMES:
                with self._isolated_hermes_environment(
                    environment,
                    server,
                    allow_data_training=self.spec.allow_data_training,
                ) as isolated:
                    environment = isolated
                    return invoke()
            return invoke()

    @staticmethod
    @contextlib.contextmanager
    def _isolated_hermes_environment(
        extra: dict[str, str],
        server: ToolServer | None,
        *,
        allow_data_training: bool = False,
    ):
        """Give Hermes an ephemeral profile that reuses only its installed runtime.

        Hermes scopes dependency environments to the data root containing ``profiles/``.
        A profile below that root therefore keeps the installed CLI usable while isolating
        config, sessions, skills, and native memory.  An unrelated temporary HERMES_HOME would
        instead be treated as a new installation and try to provision dependencies per Write.
        """
        source = {**os.environ, **extra}
        root = Driver._hermes_data_root(source)
        profiles = root / "profiles"
        profiles.mkdir(parents=True, exist_ok=True)
        home = pathlib.Path(tempfile.mkdtemp(prefix="mnemobun-", dir=profiles))
        configured: dict[str, object] = {}
        if server is not None:
            from .hermes import HermesTransport

            toolset = HermesTransport.toolset(server)
            configured["mcp_servers"] = {
                toolset: {
                    "command": server.command,
                    "args": list(server.args),
                    "enabled": True,
                    "tools": {
                        "include": list(server.tools),
                        "resources": False,
                        "prompts": False,
                    },
                }
            }
        if allow_data_training:
            configured["security"] = {"allow_data_training_tiers_noninteractive": True}
        real_home = str(source.get("HERMES_HOME") or root)
        configured = _merge_provider_settings(configured, real_home)
        _copy_credentials(real_home, home)
        try:
            target = home / "config.yaml"
            target.write_text(
                json.dumps(configured, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            yield {
                **extra,
                "HERMES_HOME": str(home),
                "HERMES_DISABLE_LAZY_INSTALLS": "1",
            }
        finally:
            shutil.rmtree(home, ignore_errors=True)

    @staticmethod
    def _hermes_data_root(environment: dict[str, str]) -> pathlib.Path:
        configured = environment.get("HERMES_HOME", "").strip()
        if configured:
            home = pathlib.Path(os.path.expandvars(configured)).expanduser()
            return home.parent.parent if home.parent.name == "profiles" else home
        suffix = environment.get("HERMES_DATA_DIR_SUFFIX", "")
        if os.name == "nt":
            local = environment.get("LOCALAPPDATA", "").strip()
            base = pathlib.Path(local) if local else pathlib.Path.home() / "AppData" / "Local"
            return base / f"hermes{suffix}"
        user_home = pathlib.Path(environment.get("HOME", str(pathlib.Path.home()))).expanduser()
        return user_home / f".hermes{suffix}"

    def _with_pins(self, system_prompt: str, store_root: pathlib.Path | None) -> str:
        """Prepend the pinned-rules block for a headless host. Never breaks a run.

        The pinned floor only survives if it reaches the host's own instructions, so it is
        delivered per run here. A memory fault degrades to "no pins" and is logged, because a
        lost rule must never cost the caller its work.
        """
        if store_root is None:
            return system_prompt
        try:
            from mnemobun.adapters import pin_channel
            from mnemobun.core.config import Config
            from mnemobun.core.store import Store

            store = Store(store_root, config=Config.default(), agent="executor")
            block = pin_channel.executor_block(store, self.spec.name)
        except Exception as error:  # noqa: BLE001 - a broken store must not abort the host run
            LOGGER.warning("mnemobun: pinned block skipped for %s: %s", self.spec.name, error)
            return system_prompt
        return f"{block}\n\n{system_prompt}" if block else system_prompt

    def _attempt(
        self,
        prompt: str,
        store_root: pathlib.Path | None,
        tools_enabled: bool,
        system_prompt: str,
        max_turns: int,
        workdir: pathlib.Path | None,
        environment: dict[str, str],
        tool_pattern: str,
    ) -> DriverResult:
        system_prompt = self._with_pins(system_prompt, store_root)
        with tempfile.TemporaryDirectory() as scratch:
            scratch_path = pathlib.Path(scratch)
            answer_file = scratch_path / ANSWER_FILENAME
            command = self.transport.command(
                self.spec,
                tools_enabled=tools_enabled,
                system_prompt=system_prompt,
                max_turns=max_turns,
                store_root=store_root,
                answer_file=answer_file,
                tool_pattern=tool_pattern,
                workdir=workdir,
            )
            needs_scratch = environment.get(observation.ENV)
            if self.spec.name == HARNESS_CODEX and tools_enabled and needs_scratch:
                command += ["--add-dir", needs_scratch]
            command, payload = self.transport.invocation(
                command, prompt, system_prompt, scratch_path
            )
            if self.spec.name == HARNESS_MUSE_CODE:
                environment = self._isolated_muse_environment(environment, scratch_path)

            def invoke() -> DriverResult:
                return self._invoke(
                    command,
                    payload,
                    self._environment(store_root, environment),
                    workdir,
                    answer_file,
                )

            if self.spec.name == HARNESS_HERMES:
                with self._isolated_hermes_environment(
                    environment,
                    None,
                    allow_data_training=self.spec.allow_data_training,
                ) as isolated:
                    environment = isolated
                    return invoke()
            return invoke()

    @staticmethod
    def _isolated_muse_environment(extra: dict[str, str], scratch: pathlib.Path) -> dict[str, str]:
        """Keep personal Muse context out while reusing credential and provider routing."""
        source = {**os.environ, **extra}
        source_home = pathlib.Path(source.get("HOME", "~")).expanduser()
        source_config = pathlib.Path(source.get("XDG_CONFIG_HOME") or source_home / ".config")
        configured_settings = source.get(MUSE_SETTINGS_ENV_VAR, "").strip()
        source_settings = (
            pathlib.Path(configured_settings).expanduser()
            if configured_settings
            else source_config / "muse" / "settings.json"
        )
        auth_path = pathlib.Path(
            source.get("MUSE_AUTH_PATH") or source_settings.with_name("auth.json")
        ).expanduser()
        home = scratch / "muse-home"
        config = scratch / "muse-config"
        data = scratch / "muse-data"
        for path in (home, config, data):
            path.mkdir()
        Driver._stage_muse_routing(source_settings, config)
        staged_auth = Driver._stage_muse_auth(auth_path, config)
        return {
            **extra,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_DATA_HOME": str(data),
            "MUSE_AUTH_PATH": str(staged_auth),
            "MUSE_NO_AUTO_UPDATE": "1",
        }

    @staticmethod
    def _stage_muse_auth(source: pathlib.Path, config_home: pathlib.Path) -> pathlib.Path:
        if not source.is_file():
            return source
        target = config_home / "muse" / "auth.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        return target

    @staticmethod
    def _stage_muse_routing(source: pathlib.Path, config_home: pathlib.Path) -> None:
        """Copy only deterministic transport fields; hooks and personal settings stay out."""
        try:
            parsed = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(parsed, dict):
            return
        allowed = ("schema_version", "provider", "model", "endpoint_transport")
        routing = {key: parsed[key] for key in allowed if key in parsed}
        if not routing:
            return
        target = config_home / "muse" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(routing, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _stage_muse_tool_server(environment: dict[str, str], server: ToolServer) -> None:
        config_home = pathlib.Path(environment["XDG_CONFIG_HOME"])
        target = config_home / "muse" / "settings.json"
        try:
            settings = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        settings["schema_version"] = 1
        settings["mcp_servers"] = {
            server.name: {
                "transport": "stdio",
                "command": server.command,
                "args": list(server.args),
                "enabled": True,
                "mode": "required",
            }
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _invoke(
        self,
        command: list[str],
        payload: str,
        environment: dict[str, str],
        workdir: pathlib.Path | None,
        answer_file: pathlib.Path,
        require_answer: bool = True,
        timeout_seconds: float | None = None,
    ) -> DriverResult:
        started = time.monotonic()
        command = [shutil.which(command[0]) or command[0], *command[1:]]
        evidence = environment.get(observation.ENV)
        attempt_id = str(time.time_ns())

        def capture(**data):
            if evidence:
                observation.emit(
                    "host_attempt",
                    directory=evidence,
                    channel="host",
                    attempt_id=attempt_id,
                    host=self.spec.name,
                    **data,
                )

        capture(state="started")
        if evidence:
            environment = {**environment, observation.ATTEMPT_ENV: attempt_id}
        phase_trace = None
        try:
            timeout = timeout_seconds or self.spec.timeout_seconds
            if self.spec.name == HARNESS_CODEX and "--json" in command:
                completed, phase_trace = _run_codex_jsonl(
                    command,
                    payload,
                    timeout=timeout,
                    environment=environment,
                    workdir=workdir,
                    started=started,
                )
            else:
                completed = subprocess.run(
                    command,
                    input=payload,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=timeout,
                    env=environment,
                    cwd=str(workdir) if workdir else None,
                    check=False,
                )
        except subprocess.TimeoutExpired as error:

            def decoded(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

            capture(state="timeout", stdout=decoded(error.stdout), stderr=decoded(error.stderr))
            return DriverResult("", False, time.monotonic() - started, "timeout")
        except OSError as error:
            capture(state="error", error_type=type(error).__name__)
            return DriverResult("", False, time.monotonic() - started, str(error))
        elapsed = time.monotonic() - started
        phases = phase_trace.phases(started + elapsed) if phase_trace else None
        capture(
            state="completed",
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if completed.returncode != 0:
            detail = (completed.stderr.strip() or completed.stdout.strip())[:ERROR_EXCERPT]
            if (
                self.spec.name == HARNESS_HERMES
                and "--toolsets" in command
                and (
                    "unrecognized arguments" in detail
                    or "unknown option" in detail
                    or "invalid choice" in detail
                )
            ):
                detail = HERMES_NATIVE_TOOL_REQUIREMENT
            if (
                self.spec.name == HARNESS_MUSE_CODE
                and MUSE_TOOLSET_SETTING in " ".join(command)
                and ("unexpected argument '-c'" in detail or "unknown option" in detail)
            ):
                detail = MUSE_NATIVE_TOOL_REQUIREMENT
            return DriverResult("", False, elapsed, detail or "non-zero exit with no output")
        text = self.transport.answer(completed.stdout, answer_file)
        if require_answer and self.spec.name in (HARNESS_CODEX, HARNESS_MUSE_CODE) and not text:
            label = "Codex" if self.spec.name == HARNESS_CODEX else "Muse"
            return DriverResult("", False, elapsed, f"missing or empty {label} final message")
        return DriverResult(
            text,
            True,
            elapsed,
            usage=self.transport.usage(completed.stdout),
            phases=phases,
        )

    def _environment(
        self, store_root: pathlib.Path | None, extra: dict[str, str]
    ) -> dict[str, str]:
        """The memory system's own variables win; the store root is the native default."""
        environment = dict(os.environ)
        if store_root is not None:
            environment["MNEMOBUN_STORE"] = str(store_root)
        environment.update(extra)
        for binary in (self.spec.binary, "mnemobun"):
            found = shutil.which(binary)
            if found:
                environment["PATH"] = f"{pathlib.Path(found).parent}:{environment.get('PATH', '')}"
        if self.credentials is not None:
            environment.update(self.credentials.environment())
        return environment
