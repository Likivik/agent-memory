"""mnemobun — Hermes memory-provider plugin (P10, docs/plans/hermes-plugin.md).

Deployment: this directory is self-contained. `lib/` carries the vendored
`mnemobun` packages (copied by scripts/build_plugin.py); the bootstrap below
prepends it to sys.path so the plugin works against a read-only Nix Hermes with
no extra install step (decision D1).

Activation: `memory.provider: mnemobun` in config.yaml. Rollback: set it
back to `default` (D8) — this plugin never deletes store data.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from mnemobun.core.store import Store  # noqa: E402
from mnemobun.executor.hermes_provider import (  # noqa: E402
    PROVIDER_NAME,
    HermesMemoryProvider,
)
from mnemobun.mcp.tools import catalogue, dispatch  # noqa: E402

# Host base class: present in Hermes, absent in a bare fork checkout — the class
# degrades to object so the fork's unit tests run without the Hermes package.
try:  # pragma: no cover - depends on the host environment
    from agent.memory_provider import MemoryProvider, RecallStatus

    _HOST_BASE: type = MemoryProvider
except Exception:  # pragma: no cover
    MemoryProvider = object  # type: ignore[assignment, misc]

    class RecallStatus:  # minimal stand-in for the host dataclass
        def __init__(self, provider_label: str, count: int, glyph: str = "M") -> None:
            self.provider_label = provider_label
            self.count = count
            self.glyph = glyph

    _HOST_BASE = object  # type: ignore[assignment]

DEFAULT_STORE_DIRNAME = "mnemobun-store"
CONFIG_FILENAME = "mnemobun-plugin.json"


class AgentMemoryHermesProvider(_HOST_BASE):
    """The released-Hermes MemoryProvider ABC, backed by this fork's engine.

    Multiplexing contract (agent_init_memory_provider): the gateway builds a
    fresh instance per message — all expensive work is lazy and instance-bound;
    nothing is cached at module level.
    """

    def __init__(self) -> None:
        self._store: Store | None = None
        self._store_path: str | None = None
        self._session_id: str = ""
        self._hermes_home: str | None = None
        self._unavailable: str | None = None
        self._last_recall_count = 0

    # -- config (D2: config field store_path; env honoured, config wins) ----
    def _config_path(self, hermes_home: str | None) -> Path:
        base = Path(hermes_home) if hermes_home else _default_home()
        return base / CONFIG_FILENAME

    def _resolve_store_path(self, hermes_home: str | None) -> Path:
        import os

        env = os.environ.get("AGENT_MEMORY_STORE")
        if env:
            return Path(env)
        try:
            raw = json.loads(self._config_path(hermes_home).read_text(encoding="utf-8"))
            if raw.get("store_path"):
                return Path(str(raw["store_path"]))
        except Exception:
            pass
        base = Path(hermes_home) if hermes_home else _default_home()
        return base / DEFAULT_STORE_DIRNAME

    # -- lifecycle ----------------------------------------------------------
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        try:
            return self._ensure_store()
        except Exception as exc:  # a broken store must degrade, not crash the agent
            self._unavailable = f"store unavailable: {exc}"
            return False

    def unavailable_reason(self) -> str:
        return self._unavailable or "not initialised"

    def initialize(self, session_id: str, **kwargs: object) -> bool:
        self._session_id = str(session_id or "")
        self._hermes_home = kwargs.get("hermes_home")  # type: ignore[assignment]
        return self.is_available()

    def _ensure_store(self) -> bool:
        if self._store is not None:
            return True
        path = self._resolve_store_path(self._hermes_home)
        if not path.exists():
            self._unavailable = f"store not found: {path}"
            return False
        self._store_path = str(path)
        self._store = Store(root=path)
        self._provider_instance = HermesMemoryProvider(store=self._store, reasoner=None)
        return True

    def _provider(self) -> HermesMemoryProvider:
        """The engine wrapper; one instance per plugin instance (multiplexing contract)."""
        assert self._provider_instance is not None
        return self._provider_instance

    # -- read side -----------------------------------------------------------
    def system_prompt_block(self) -> str:
        return (
            "Memory is available (mnemobun). Verify claims you rely on with"
            " memory_verify; record durable beliefs as claims (they start"
            " `proposed` and are accepted only after a ruling)."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._ensure_store():
            return ""
        text = self._provider().prefetch(query, session_id=session_id or self._session_id)
        self._last_recall_count = self._provider().last_recall_count
        return text

    def recall_status(self):
        return RecallStatus(provider_label=PROVIDER_NAME, count=self._last_recall_count)

    # -- write side ----------------------------------------------------------
    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages=None,
        turn_author=None,
    ) -> None:
        if not self._ensure_store():
            return
        self._provider().sync_turn(
            user_content, assistant_content, session_id=session_id or self._session_id
        )

    # -- tool surface (D6: catalogue/dispatch passthrough, no renames) -------
    def get_tool_schemas(self) -> list[dict]:
        return catalogue()

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if not self._ensure_store():
            return json.dumps({"error": self._unavailable or "store unavailable"})
        try:
            return json.dumps(dispatch(self._store, tool_name, dict(args or {})))
        except Exception as exc:
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    # -- hooks ----------------------------------------------------------------
    def on_session_end(self, messages) -> None:  # sessions are endless; no-op (D4)
        return None

    def identity_signature(self) -> dict:
        return {
            "provider": PROVIDER_NAME,
            "store": self._store_path or self._resolve_store_path(self._hermes_home).as_posix(),
        }

    # -- config surface --------------------------------------------------------
    def get_config_schema(self) -> list[dict]:
        return [
            {
                "name": "store_path",
                "type": "string",
                "description": "Filesystem path of the mnemobun store",
            }
        ]

    def save_config(self, values: dict, hermes_home: str) -> None:
        path = self._config_path(hermes_home)
        current: dict = {}
        with contextlib.suppress(Exception):
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update({k: v for k, v in values.items() if k in {"store_path"}})
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    def read_config_fields(self, hermes_home: str) -> dict:
        try:
            raw = json.loads(self._config_path(hermes_home).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {k: v for k, v in raw.items() if k in {"store_path"}}

    def write_config_fields(self, values: dict, hermes_home: str) -> None:
        self.save_config(values, hermes_home)

    def backup_paths(self) -> list[str]:
        return [self._store_path or self._resolve_store_path(self._hermes_home).as_posix()]

    # -- dream (HP4): the idle task body; registration is host-side -----------
    def dream_tick(self, run) -> str | None:
        """Called by the registered idle task. Deterministic sleep only (D4).

        ``run`` is the host's IdleTaskRun; its ``run_count`` is a monotonic
        stand-in for ``sessions_since`` so ``Manage.due`` keeps its semantics.
        """
        if not self._ensure_store():
            return None
        sessions_since = getattr(run, "run_count", 0)
        report = self._provider().run_sleep(sessions_since)
        if report.get("skipped"):
            return None
        return "deterministic sleep ran (proposals queued, none ruled)"


def _default_home() -> Path:
    import os

    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


provider = AgentMemoryHermesProvider()


def register(ctx) -> None:
    """Loader hook: the released loader calls ``register(ctx)`` before the
    subclass scan and passes a real PluginContext — this is the only way a
    memory plugin reaches host surfaces like ``register_idle_task`` (HP4/D4)."""
    with contextlib.suppress(Exception):
        ctx.register_memory_provider(provider)  # else loader falls through to the subclass scan
    try:
        ctx.register_idle_task(
            "dream",
            provider.dream_tick,
            interval_hours=24,
            min_idle_hours=1,
            first_run="defer",
        )
    except Exception as error:
        import logging

        logging.getLogger(__name__).warning(
            "mnemobun: idle-task dream registration unavailable: %s", error
        )
