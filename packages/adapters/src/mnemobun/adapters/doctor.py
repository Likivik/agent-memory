"""Read-only harness preflight with stable failure codes."""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import tempfile
import tomllib

from mnemobun.core import health as health_events
from mnemobun.core import prompts, timestamp, write_jobs
from mnemobun.core.config import PINNED_REFUSED_STANDING
from mnemobun.core.route import resolve_route
from mnemobun.core.store import Store

from . import moments, openrouter, setup

READY = "READY"
FAILED = "FAILED"


@dataclasses.dataclass(frozen=True)
class Check:
    code: str
    ok: bool
    detail: str
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Report:
    harness: str
    store: pathlib.Path
    settings: pathlib.Path
    checks: tuple[Check, ...]
    version: str = ""

    @property
    def status(self) -> str:
        return FAILED if any(not item.ok and item.required for item in self.checks) else READY

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "harness": self.harness,
            "version": self.version,
            "store": str(self.store),
            "settings": str(self.settings),
            "checks": [item.as_dict() for item in self.checks],
        }


def smoke(store: Store, harness: str = "", model: str = "") -> dict[str, object]:
    """One trivial spawn through the production reasoner path: the auth gate.

    Proves LLM credentials reach the isolated sandbox profile (P13.4 blocker).
    Exactly one model call; exposed as `doctor --smoke` and the live system
    suite's test_auth_smoke.
    """
    import os

    from mnemobun.adapters import openrouter
    from mnemobun.executor import distiller as distiller_module
    from mnemobun.executor import selection

    # The production spawn inherits provider keys from the gateway environment.
    # Standalone runs (CLI, tests) carry none: detect the stored credential and
    # inject it the same way the live system suite does.
    credential = openrouter.detect_credential()
    if credential is not None and not os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = credential.value

    config = selection.resolve(
        store.config.executor, "write", reasoner=harness, model=model
    )
    try:
        from mnemobun.executor.reasoners import DriverReasoner

        ask = DriverReasoner.for_harness(config.reasoner, model=config.model)
        reasoner = distiller_module.distiller(config, store=store, ask=ask)
        answer = reasoner("Reply with exactly the two letters: OK")
    except Exception as error:  # the doctor reports, it does not crash
        return {"answered": False, "answer": "", "reason": f"{type(error).__name__}: {error}"}
    return {"answered": bool(answer and answer.strip()), "answer": answer[:200]}


def run(
    store: Store,
    harness: str,
    *,
    settings_path: pathlib.Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    mcp: bool = False,
    live: bool = True,
    environment: dict[str, str] | None = None,
) -> Report:
    harness = setup.canonical_host(harness)
    target = settings_path or setup.default_settings_path(harness, environment)
    checks: list[Check] = []
    version = ""
    try:
        version = setup.probe(harness)
        checks.append(Check("DRIVER_BINARY_OK", True, version))
    except Exception as error:
        # An endpoint reasoner never runs the harness binary: it posts to an
        # OpenAI-shaped URL. A missing binary is then a note about the harness,
        # not a reason to refuse the store.
        needed = _driver_binary_needed(store)
        checks.append(
            Check(
                "DRIVER_BINARY_MISSING" if needed else "DRIVER_BINARY_NOT_REQUIRED",
                not needed,
                str(error),
                required=needed,
            )
        )
    checks.extend(_store_checks(store))
    checks.append(_write_jobs_check(store))
    configured = _settings(target, checks)
    if configured is not None:
        checks.extend(_hook_checks(configured, harness, store.root, target))
    skill = setup.skill_path(harness, target)
    skill_ok = False
    if skill.is_file():
        # A site may extend the skill with its own notes, so the upstream text
        # must be present rather than byte-identical. Removing or rewriting an
        # instruction still shows up here.
        skill_ok = prompts.skill().strip() in skill.read_text(encoding="utf-8").strip()
    checks.append(
        Check(
            "SKILL_OK" if skill_ok else "SKILL_INVALID",
            skill_ok,
            f"installed at {skill}" if skill.is_file() else f"missing at {skill}",
        )
    )
    checks.extend(_reasoner_checks(store, harness, environment))
    for operation in ("write", "manage"):
        checks.append(
            _live_reasoner_check(store, harness, operation)
            if live
            else Check(
                f"{operation.upper()}_LIVE_PREFLIGHT_SKIPPED",
                False,
                f"live {operation} reasoner check was explicitly skipped",
            )
        )
    if mcp:
        checks.append(_mcp_check(harness, target, store.root, configured, environment))
    if harness == moments.HARNESS_CODEX:
        checks.extend(_codex_checks(target, store.root))
    if harness == moments.HARNESS_MUSE_CODE and provider:
        checks.extend(
            _muse_provider_checks(
                configured,
                provider=provider,
                model=model,
                live=live,
                environment=environment,
            )
        )
    return Report(
        harness=harness, store=store.root, settings=target, checks=tuple(checks), version=version
    )


def _store_checks(store: Store) -> list[Check]:
    initialized = (
        store.root.is_dir()
        and store.layout.schemas_dir.is_dir()
        and (store.root / "config.toml").is_file()
    )
    checks = [
        Check(
            "STORE_INITIALIZED" if initialized else "STORE_NOT_INITIALIZED",
            initialized,
            str(store.root),
        )
    ]
    writable = False
    detail = str(store.root)
    if initialized:
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".doctor-", dir=store.layout.state_dir)
            os.close(descriptor)
            pathlib.Path(temporary).unlink()
            writable = True
        except OSError as error:
            detail = f"{store.root}: {error}"
    checks.append(Check("STORE_WRITABLE" if writable else "STORE_NOT_WRITABLE", writable, detail))
    summary = health_events.summary(store)
    counts = summary.get("counts") or {}
    failures = int(counts.get("capture_failed", 0))
    checks.append(
        Check(
            "CAPTURE_HEALTHY" if failures == 0 else "CAPTURE_FAILURES",
            failures == 0,
            f"capture_failed={failures} dedupe_refused={int(counts.get('dedupe_refused', 0))}",
            required=False,
        )
    )
    route = resolve_route(store, None).route
    checks.append(
        Check(
            "ROUTE_SET" if route.is_set else "ROUTE_UNSET",
            route.is_set,
            route.label() or "unset - deterministic-only",
            required=False,
        )
    )
    checks.extend(_pinned_checks(store))
    return checks


def _pinned_checks(store: Store) -> list[Check]:
    """The pinned floor: size, staleness, readability, and whether a harness can honour it."""
    from mnemobun.core import pinned as pinned_rules

    out: list[Check] = []
    try:
        block = pinned_rules.block(store)
    except Exception as error:  # unreadable roster or a vanished pinned record
        out.append(Check("PINNED_UNREADABLE", False, str(error), required=False))
        return out
    budget = store.config.recall.pinned_max_bytes
    out.append(
        Check(
            "PINNED_BUDGET",
            not block.omitted,
            f"{len(block.rules)} rule(s), {block.omitted} omitted, cap {budget} bytes",
            required=False,
        )
    )
    stale = [
        record.name
        for record in store.records()
        if pinned_rules.is_pinned(record) and record.standing in PINNED_REFUSED_STANDING
    ]
    out.append(
        Check(
            "PINNED_STANDING",
            not stale,
            ", ".join(stale) or "every pinned rule still stands",
            required=False,
        )
    )
    try:
        from mnemobun.adapters import channels

        channel = channels.for_harness("hermes")
        delivered = channels.recorded(store.layout.state_dir).get(channel.harness, "")
        current = block.digest
        out.append(
            Check(
                "PIN_DIGEST",
                delivered == current,
                f"delivered={delivered[:12] or 'never'} current={current[:12]}",
                required=False,
            )
        )
        out.append(
            Check(
                "PIN_CHANNEL",
                not channel.degraded,
                f"{channel.harness}: {channel.surface} (preserved={channel.preserved})",
                required=False,
            )
        )
    except Exception as error:  # the channel registry must never break doctor
        out.append(Check("PIN_CHANNEL_UNREADABLE", False, str(error), required=False))
    return out


def _write_jobs_check(store: Store) -> Check:
    """A stuck or dying Write queue is an operational warning, not a setup refusal."""
    queue = write_jobs.WriteJobs(store)
    now = store.clock.now()
    queued = running = stuck = dead = failed = 0
    for job in queue.list():
        if job.state == write_jobs.STATE_QUEUED:
            queued += 1
        elif job.state == write_jobs.STATE_RUNNING:
            running += 1
            stuck += 1 if _lease_expired(job, now) else 0
        elif job.state == write_jobs.STATE_DEAD:
            dead += 1
        elif job.state == write_jobs.STATE_FAILED:
            failed += 1
    quarantined = len(queue.quarantined())
    if dead or failed or stuck or quarantined:
        return Check(
            "WRITE_JOBS_DEGRADED",
            False,
            f"{dead} dead, {failed} failed, {stuck} with an expired lease, "
            f"{quarantined} quarantined",
            required=False,
        )
    return Check("WRITE_JOBS_HEALTHY", True, f"{queued} queued, {running} running", required=False)


def _lease_expired(job, now) -> bool:
    try:
        return timestamp.parse(job.lease_until) < now if job.lease_until else True
    except ValueError:
        return True


def _settings(target: pathlib.Path, checks: list[Check]) -> dict[str, object] | None:
    if not target.is_file():
        checks.append(Check("HOST_CONFIG_INVALID", False, f"missing {target}"))
        return None
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        checks.append(Check("HOST_CONFIG_INVALID", False, f"{target}: {error}"))
        return None
    if not isinstance(parsed, dict):
        checks.append(Check("HOST_CONFIG_INVALID", False, f"{target} is not a JSON object"))
        return None
    checks.append(Check("HOST_CONFIG_OK", True, str(target)))
    return parsed


def _hook_checks(
    configured: dict[str, object],
    harness: str,
    store_root: pathlib.Path,
    settings_path: pathlib.Path,
) -> list[Check]:
    hooks = configured.get(setup.HOOKS_KEY)
    if not isinstance(hooks, dict):
        return [Check("HOOK_INVALID", False, "settings.hooks is missing or not an object")]
    expected_store = setup.render_command([str(store_root.resolve())])
    failures = []
    for event in moments.MOMENTS[harness]:
        entries = hooks.get(event)
        if not isinstance(entries, list):
            failures.append(f"{event} missing")
            continue
        managed = [entry for entry in entries if setup.HOOK_COMMAND in json.dumps(entry)]
        if len(managed) != 1:
            failures.append(f"{event} has {len(managed)} managed hooks")
            continue
        if not _mentions(managed[0], expected_store):
            failures.append(f"{event} does not pin Store {expected_store}")
            continue
        if harness == moments.HARNESS_MUSE_CODE:
            expected_settings = setup.render_command([str(settings_path.resolve())])
            if not _mentions(managed[0], setup.MUSE_SETTINGS_FLAG) or not _mentions(
                managed[0], expected_settings
            ):
                failures.append(f"{event} does not pin Muse settings {expected_settings}")
    return [
        Check(
            "HOOK_OK" if not failures else "HOOK_INVALID",
            not failures,
            "all lifecycle hooks installed once" if not failures else "; ".join(failures),
        )
    ]


def _mentions(entry: object, text: str) -> bool:
    return json.dumps(text)[1:-1] in json.dumps(entry)


def _reasoner_checks(
    store: Store, harness: str, environment: dict[str, str] | None = None
) -> list[Check]:
    from mnemobun.core.config import REASONER_DRIVERS
    from mnemobun.executor import selection

    checks = []
    for operation in selection.OPERATIONS:
        label = operation.upper()
        try:
            executor = selection.resolve(
                store.config.executor,
                operation,

            )
            if executor.reasoner in REASONER_DRIVERS:
                ok = True
                detail = f"{operation} reasons through the {executor.reasoner} CLI"
            else:
                ok = False
                detail = (
                    f"{operation} reasoner must name a driver or 'plugin': "
                    f"{executor.reasoner!r}"
                )
        except Exception as error:
            ok = False
            detail = f"{operation} reasoner configuration failed: {error}"
        checks.append(
            Check(
                f"{label}_REASONER_AVAILABLE" if ok else f"{label}_REASONER_UNAVAILABLE",
                ok,
                detail,
            )
        )
    return checks


def _live_reasoner_check(store: Store, harness: str, operation: str) -> Check:
    """Exercise the executor selected for one channel, with one bounded attempt."""
    try:
        from mnemobun.executor import selection
        from mnemobun.executor.distiller import distiller

        executor = selection.resolve(
            store.config.executor,
            operation,

        )
        from mnemobun.executor.reasoners import DriverReasoner

        ask = DriverReasoner.for_harness(executor.reasoner, model=executor.model)
        reasoner = distiller(executor, store=store, ask=ask)
        reply = reasoner("Reply with exactly MNEMOBUN_READY.")
    except Exception as error:
        return Check(
            f"{operation.upper()}_REASONER_UNAVAILABLE",
            False,
            f"live {operation} reasoner probe failed: {type(error).__name__}",
        )
    ok = _probe_matched(reply)
    return Check(
        (
            f"{operation.upper()}_REASONER_LIVE_OK"
            if ok
            else f"{operation.upper()}_REASONER_UNAVAILABLE"
        ),
        ok,
        (
            f"{operation} reasoner completed a live request"
            if ok
            else f"live {operation} reasoner returned no READY"
        ),
    )


def _driver_binary_needed(store: Store) -> bool:
    """Whether any channel would actually launch the harness binary.

    Every channel resolves to the harness reasoner, so the harness binary is what
    reasons and its absence is a loud failure, not a silent abstain.
    """
    from mnemobun.core.config import REASONER_DRIVERS

    executor = store.config.executor
    for policy in (executor.write, executor.manage):
        if (policy.reasoner or executor.reasoner) in REASONER_DRIVERS:
            return True
    return False


def _probe_matched(reply: str) -> bool:
    """Whether the probe reply carries the readiness token.

    The probe asks an OpenAI-compatible endpoint to echo one fixed token. Some
    gateways occasionally splice a stray character into a short echoed string,
    which says nothing about whether the endpoint is usable. Compare on letters
    alone before declaring the endpoint unavailable.
    """
    if "MNEMOBUN_READY" in reply:
        return True
    return "AGENTMEMORYREADY" in re.sub(r"[^A-Za-z]", "", reply).upper()


def _mcp_check(
    harness: str,
    target: pathlib.Path,
    store_root: pathlib.Path,
    configured: dict[str, object] | None,
    environment: dict[str, str] | None,
) -> Check:
    if harness == moments.HARNESS_CODEX:
        binary = setup.BINARIES[harness]
        env = {
            **(os.environ if environment is None else environment),
            "CODEX_HOME": str(target.parent),
        }
        try:
            result = subprocess.run(
                [binary, "mcp", "get", setup.MCP_SERVER, "--json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return Check("MCP_INVALID", False, str(error))
        rendered = result.stdout + result.stderr
        ok = (
            result.returncode == 0
            and setup.mcp_binary() in rendered
            and str(store_root) in rendered
        )
        return Check("MCP_OK" if ok else "MCP_INVALID", ok, "Codex MCP server configuration")
    key = "mcp_servers"
    candidate = configured.get(key) if isinstance(configured, dict) else None
    servers = candidate if isinstance(candidate, dict) else None
    server = servers.get(setup.MCP_SERVER) if isinstance(servers, dict) else None
    # ensure_ascii=False keeps a non-ASCII path readable, so a harness whose
    # install path is not plain ASCII is still matched.
    rendered = json.dumps(server, ensure_ascii=False) if server is not None else ""
    ok = setup.mcp_binary() in rendered and str(store_root.resolve()) in rendered
    return Check("MCP_OK" if ok else "MCP_INVALID", ok, f"{setup.MCP_SERVER} stdio server")


def _mcp_servers(target: pathlib.Path, key: str) -> dict[str, object] | None:
    """The MCP servers a harness keeps on disk, found where that harness keeps them.

    The installer writes one file, but the setting a harness actually reads is not
    always that one: a harness may keep its MCP configuration beside its settings
    instead of in the home directory. Look in both places before reporting the
    server as absent.
    """
    for path in (target.parent / "mcp.json",):
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = found.get(key) if isinstance(found, dict) else None
        if isinstance(servers, dict) and servers:
            return servers
    return None


def _codex_checks(target: pathlib.Path, store_root: pathlib.Path) -> list[Check]:
    config = target.parent / "config.toml"
    checks: list[Check] = []
    if config.is_file():
        try:
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            return [Check("HOST_CONFIG_INVALID", False, f"{config}: {error}")]
        features = parsed.get("features", {})
        enabled = not isinstance(features, dict) or features.get("hooks", True) is not False
        checks.append(
            Check(
                "CODEX_HOOKS_ENABLED" if enabled else "HOOK_INVALID",
                enabled,
                "Codex hooks feature enabled" if enabled else "features.hooks=false",
            )
        )
        sandbox = parsed.get("sandbox_mode", "")
        if sandbox == "read-only":
            checks.append(
                Check(
                    "CODEX_SANDBOX_STORE_ACCESS",
                    False,
                    f"default sandbox is read-only; Store writes require access to {store_root}",
                    required=False,
                )
            )
        workspace = parsed.get("sandbox_workspace_write", {})
        raw_roots = workspace.get("writable_roots", []) if isinstance(workspace, dict) else []
        roots = raw_roots if isinstance(raw_roots, list) else []
        resolved_store = store_root.resolve()
        store_allowed = any(
            isinstance(root, str)
            and resolved_store.is_relative_to(pathlib.Path(root).expanduser().resolve())
            for root in roots
        )
        checks.append(
            Check(
                "CODEX_STORE_ACCESS_CONFIGURED" if store_allowed else "CODEX_STORE_ACCESS_REVIEW",
                store_allowed,
                (
                    f"workspace-write includes Store {resolved_store}"
                    if store_allowed
                    else (
                        f"agent commands that query Store {resolved_store} need --add-dir "
                        "or sandbox_workspace_write.writable_roots; setup does not expand "
                        "sandbox permissions automatically"
                    )
                ),
                required=False,
            )
        )
    checks.append(
        Check(
            "CODEX_HOOK_TRUST_REVIEW",
            False,
            "Codex may require one-time review of this non-managed user hook",
            required=False,
        )
    )
    return checks


def _muse_provider_checks(
    configured: dict[str, object] | None,
    *,
    provider: str,
    model: str | None,
    live: bool,
    environment: dict[str, str] | None,
) -> list[Check]:
    if provider != openrouter.PROVIDER:
        return [Check("HOST_CONFIG_INVALID", False, f"unsupported provider {provider!r}")]
    target = model or openrouter.DEFAULT_MODEL
    expected_model = target.removeprefix("meta/")
    routing_ok = bool(
        configured
        and configured.get("provider") == openrouter.MUSE_PROVIDER
        and configured.get("model") == expected_model
        and configured.get("endpoint_transport")
        == {"base_url": openrouter.DEFAULT_PROXY_URL, "auth": "bearer"}
    )
    checks = [
        Check(
            "PROVIDER_ROUTING_OK" if routing_ok else "HOST_CONFIG_INVALID",
            routing_ok,
            "Muse meta transport routes through the local OpenRouter bridge",
        )
    ]
    credential = openrouter.detect_credential(environment)
    checks.append(
        Check(
            "OPENROUTER_CREDENTIAL_OK" if credential else "OPENROUTER_CREDENTIAL_MISSING",
            credential is not None,
            (
                f"detected from {credential.source}"
                if credential
                else "set OPENROUTER_API_KEY or use muse auth"
            ),
        )
    )
    proxy_ok = openrouter.proxy_health(environment=environment)
    checks.append(
        Check(
            "PROXY_REACHABLE" if proxy_ok else "PROXY_UNREACHABLE",
            proxy_ok,
            openrouter.DEFAULT_PROXY_URL,
        )
    )
    if credential and live:
        code, detail = openrouter.openrouter_preflight(
            credential, model=target, environment=environment
        )
        checks.append(Check(code or "OPENROUTER_OK", code is None, detail))
        if code is None and proxy_ok:
            live_code, live_detail = openrouter.muse_live_preflight(
                credential, model=target, environment=environment
            )
            checks.append(Check(live_code or "MUSE_LIVE_OK", live_code is None, live_detail))
    elif not live:
        checks.append(
            Check(
                "LIVE_PREFLIGHT_SKIPPED",
                False,
                "live OpenRouter and Muse checks were explicitly skipped",
            )
        )
    return checks
