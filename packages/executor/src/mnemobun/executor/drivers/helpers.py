"""Trace parsing, credential staging and provider settings: the shared vocabulary both sides use."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import threading
import time

from .types import DriverPhases

PROVIDER_CONFIG_ALLOWLIST = (
    "model",  # model routing: base_url, defaults, provider endpoints
    "model_providers",
    "providers",
    "custom_providers",
    "fallback_providers",
    "custom_endpoints",
    "default_model",
)


def _load_real_config(real_home: str) -> dict[str, object]:
    """The user's real Hermes config, parsed leniently (their YAML, our JSON)."""
    if not real_home:
        return {}
    try:
        text = (pathlib.Path(real_home) / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        loaded: object = json.loads(text)
    except ValueError:
        try:
            import yaml
        except ImportError:
            return {}
        try:
            loaded = yaml.safe_load(text)
        except Exception:
            return {}
    return loaded if isinstance(loaded, dict) else {}


def _merge_provider_settings(
    configured: dict[str, object], real_home: str
) -> dict[str, object]:
    """Seed provider-relevant settings from the real profile (settings-drift fix).

    Only an explicit allowlist crosses into the sandbox: custom endpoints and
    model routing must survive isolation. Nothing else does — no plugins, no
    skills, no sessions; the sandbox must never run its own memory plugin.
    """
    real = _load_real_config(real_home)
    for key in PROVIDER_CONFIG_ALLOWLIST:
        if key in real and key not in configured:
            configured[key] = real[key]
    return configured


    # relative paths: the provider credential store lives under muse/, and the
    # Hermes provider check reads the .env file at the Hermes home.
CREDENTIAL_FILES = ("auth.json", ".anthropic_oauth.json", "muse/auth.json", ".env")


def _copy_credentials(real_home: str, sandbox_home: pathlib.Path) -> list[str]:
    """Copy the credential subset into the sandbox (P13.4 auth fallback).

    Hermes credentials do NOT resolve from the data root into a sandbox profile
    (proved by the auth smoke test: "no API keys or providers found"). Only the
    credential files cross; they live in the temp profile for the run's duration
    and are removed with it.
    """
    copied: list[str] = []
    if not real_home:
        return copied
    root_path = pathlib.Path(real_home)
    for name in CREDENTIAL_FILES:
        source = root_path / name
        try:
            if source.exists():
                target = sandbox_home / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(name)
        except OSError:
            continue
    return copied


class _CodexTrace:
    """Timestamp lifecycle JSONL as it arrives; Codex events carry no wall-clock field."""

    def __init__(self, started: float):
        self.started = started
        self.first_event: float | None = None
        self.turn_completed: float | None = None
        self.mcp_started: dict[str, float] = {}
        self.mcp_seconds = 0.0

    def observe(self, line: str, at: float) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        if self.first_event is None:
            self.first_event = at
        event_type = event.get("type")
        if event_type == "turn.completed":
            self.turn_completed = at
        if event_type not in ("item.started", "item.completed"):
            return
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            return
        item_id = item.get("id")
        if not isinstance(item_id, str):
            return
        if event_type == "item.started":
            self.mcp_started[item_id] = at
        else:
            begun = self.mcp_started.pop(item_id, None)
            if begun is not None:
                self.mcp_seconds += max(0.0, at - begun)

    def phases(self, finished: float) -> DriverPhases | None:
        if self.first_event is None or self.turn_completed is None:
            return None
        startup = max(0.0, self.first_event - self.started)
        shutdown = max(0.0, finished - self.turn_completed)
        elapsed = max(0.0, finished - self.started)
        model_wait = max(0.0, elapsed - startup - self.mcp_seconds - shutdown)
        return DriverPhases(startup, model_wait, self.mcp_seconds, shutdown)


def _run_codex_jsonl(
    command: list[str],
    payload: str,
    *,
    timeout: float,
    environment: dict[str, str],
    workdir: pathlib.Path | None,
    started: float,
) -> tuple[subprocess.CompletedProcess[str], _CodexTrace]:
    """Capture Codex JSONL receive times without exposing or persisting model content."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=str(workdir) if workdir else None,
    )
    stdout: list[str] = []
    stderr: list[str] = []
    trace = _CodexTrace(started)

    def read(stream, sink: list[str], observe: bool = False) -> None:
        for line in iter(stream.readline, ""):
            sink.append(line)
            if observe:
                trace.observe(line, time.monotonic())
        stream.close()

    assert process.stdout is not None and process.stderr is not None and process.stdin is not None
    out_thread = threading.Thread(target=read, args=(process.stdout, stdout, True), daemon=True)
    err_thread = threading.Thread(target=read, args=(process.stderr, stderr), daemon=True)
    out_thread.start()
    err_thread.start()
    try:
        process.stdin.write(payload)
        process.stdin.close()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        out_thread.join()
        err_thread.join()
        raise subprocess.TimeoutExpired(
            command, timeout, output="".join(stdout), stderr="".join(stderr)
        ) from error
    out_thread.join()
    err_thread.join()
    return (
        subprocess.CompletedProcess(command, process.returncode, "".join(stdout), "".join(stderr)),
        trace,
    )
