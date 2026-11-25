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
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

_LIB = Path(__file__).resolve().parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from mnemobun.core.settings import (  # noqa: E402
    SETTINGS_KEYS,
    apply_settings,
    effective_settings,
)
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
# The host's display reader (web_server_memory._read_memory_provider_existing_values)
# looks at $HERMES_HOME/<name>/config.json - the mirror lives exactly there.
CONFIG_DIRNAME = "mnemobun"
CONFIG_FILENAME = "config.json"


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
        return base / CONFIG_DIRNAME / CONFIG_FILENAME

    def _resolve_store_path(self, hermes_home: str | None) -> Path:
        import os

        env = os.environ.get("MNEMOBUN_STORE")
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

    def _ensure_store(self, hermes_home: str | None = None) -> bool:
        try:
            return self._ensure_store_inner(hermes_home)
        except Exception as error:
            import logging

            if type(error).__name__ == "StoreVersionError":
                logging.getLogger(__name__).error(
                    "mnemobun: VERSION MISMATCH — %s (store stays untouched)", error
                )
                self._unavailable = str(error)
                return False
            raise

    def _ensure_store_inner(self, hermes_home: str | None = None) -> bool:
        if self._store is not None:
            return True
        path = self._resolve_store_path(hermes_home or self._hermes_home)
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

    # -- model suggestions (one read-only probe, cached; never on read) -------
    def _models_cache_path(self, hermes_home: str | None = None) -> Path:
        base = self._store_path or self._resolve_store_path(hermes_home)
        return Path(base) / ".state" / "models.json"

    @staticmethod
    def _probe_models(endpoint: str, key_env: str) -> tuple[list[str], str]:
        """One read-only GET ``{endpoint}/models`` (OpenAI-compatible).

        Never raises; returns ``(models, error)``. The key comes from the env
        var named by ``key_env`` and is never printed.
        """
        import urllib.request

        base = (endpoint or "").strip().rstrip("/")
        if not base:
            return [], "no endpoint configured"
        request = urllib.request.Request(
            base + "/models", headers={"Accept": "application/json"}
        )
        key = os.environ.get(key_env.strip(), "") if (key_env or "").strip() else ""
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:  # a probe failure is data, not an error
            return [], f"{type(error).__name__}: {error}"
        rows = payload.get("data") if isinstance(payload, dict) else payload
        models = [
            str(row["id"])
            for row in rows or []
            if isinstance(row, dict) and row.get("id")
        ]
        return models, ""

    def _model_choices(self) -> list[str]:
        """``""`` (unset) + cached endpoint models + a saved value outside them.

        File reads only - the host calls this per request, so no network. An
        empty return means "no list cached": the field falls back to typing,
        because a select cannot hold values outside its options.
        """
        saved = ""
        models: list[str] = []
        with contextlib.suppress(Exception):
            raw = json.loads(
                self._config_path(self._hermes_home).read_text(encoding="utf-8")
            )
            saved = str(raw.get("model") or "")
        with contextlib.suppress(Exception):
            raw = json.loads(
                self._models_cache_path(self._hermes_home).read_text(encoding="utf-8")
            )
            models = [str(m) for m in raw.get("models") or [] if m]
        if not models:
            return []
        choices = ["", *dict.fromkeys(models)]
        if saved and saved not in choices:
            choices.append(saved)  # never drop a saved model the list lacks
        return choices

    def _refresh_model_choices(
        self, hermes_home: str | None, endpoint: str, key_env: str
    ) -> tuple[list[str], str]:
        """Probe once and cache the list; called on save, never on read."""
        models, error = self._probe_models(endpoint, key_env)
        if models:
            cache = self._models_cache_path(hermes_home)
            with contextlib.suppress(OSError):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(
                    json.dumps({"models": models, "endpoint": (endpoint or "").strip()}),
                    encoding="utf-8",
                )
        return models, error

    @staticmethod
    def _validate_endpoint(value: str) -> None:
        parsed = urlparse((value or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"endpoint is not an http(s) URL: {value!r}")

    # -- config surface --------------------------------------------------------
    def get_config_schema(self) -> list[dict]:
        # The host reads ``key`` (agent.memory_provider.MemoryProvider) and
        # drops any field without one - a schema using ``name`` renders an
        # empty panel ("does not expose dashboard settings").
        fields: list[dict] = [
            {
                "key": "model",
                "type": "text",
                "description": (
                    "LLM model for memory work. Never inherited; "
                    "empty = deterministic-only"
                ),
                "placeholder": "unset - deterministic-only, jobs refuse loudly",
            },
            {
                "key": "endpoint",
                "type": "text",
                "description": "OpenAI-compatible base URL for memory work",
                "placeholder": "https://api.example.com/v1",
            },
            {
                "key": "key_env",
                "type": "text",
                "description": "Env var name holding the endpoint API key",
            },
            {
                "key": "distill_model",
                "type": "text",
                "description": "Optional override: model for feed/distill",
            },
            {
                "key": "dream_model",
                "type": "text",
                "description": "Optional override: model for dream/review",
            },
            {
                "key": "max_calls_per_run",
                "type": "number",
                "description": "Hard cap: LLM calls per run",
            },
            {
                "key": "max_tokens_per_day",
                "type": "number",
                "description": "Hard cap: input tokens per day",
            },
            {
                "key": "store_path",
                "type": "text",
                "description": "Filesystem path of the mnemobun store",
            },
        ]
        choices = self._model_choices()
        if choices:
            # Non-empty choices render as a select (web_server_memory
            # ._schema_field_kind). '' first = explicit unset; there is no
            # default, so nothing is ever picked silently.
            fields[0]["choices"] = choices
        return fields

    def save_config(self, values: dict, hermes_home: str) -> None:
        endpoint = "" if values.get("endpoint") is None else str(values.get("endpoint")).strip()
        if "endpoint" in values and endpoint:
            self._validate_endpoint(endpoint)
        path = self._config_path(hermes_home)
        current: dict = {}
        with contextlib.suppress(Exception):
            current = json.loads(path.read_text(encoding="utf-8"))
        # Mirror every submitted non-secret field: the legacy display reader
        # sees only this flat file, while the store stays the jobs' truth.
        current.update(
            {
                k: ("" if v is None else v)
                for k, v in values.items()
                if k in SETTINGS_KEYS or k == "store_path"
            }
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        except OSError as error:
            raise ValueError(f"cannot write {path}: {error.strerror}") from error
        settings = {k: ("" if v is None else v) for k, v in values.items() if k in SETTINGS_KEYS}
        if settings:
            if not self._ensure_store(hermes_home):
                raise ValueError(self._unavailable or "store not found")
            apply_settings(self._store, settings, actor="gui")
        # Suggestions: one read-only probe when an endpoint is configured.
        # A failed probe never fails the save (settings are already durable).
        effective_endpoint = endpoint or str(current.get("endpoint") or "")
        key_env = str(values.get("key_env") or current.get("key_env") or "")
        if effective_endpoint:
            with contextlib.suppress(Exception):
                self._refresh_model_choices(hermes_home, effective_endpoint, key_env)

    def read_config_fields(self, hermes_home: str) -> dict:
        """Pull: display reads the store (single source), not a cached copy."""
        fields: dict = {}
        try:
            raw = json.loads(self._config_path(hermes_home).read_text(encoding="utf-8"))
            fields.update({k: v for k, v in raw.items() if k in {"store_path"}})
        except Exception:
            pass
        if self._ensure_store(hermes_home):
            fields.update(effective_settings(self._store))
        placeholders: dict = {}
        if not fields.get("model"):
            placeholders["model"] = "unset - deterministic-only, jobs refuse loudly"
        return {"values": fields, "placeholders": placeholders}

    def write_config_fields(self, values: dict, hermes_home: str) -> None:
        self.save_config(values, hermes_home)

    def post_setup(self, hermes_home: str, config: dict) -> None:
        """Wizard hook: probe the endpoint once, print model suggestions.

        Nothing is ever selected for the user - the list is a suggestion only.
        """
        endpoint = str(config.get("endpoint") or "").strip()
        key_env = str(config.get("key_env") or "").strip()
        if not endpoint:
            return
        models, error = self._refresh_model_choices(hermes_home, endpoint, key_env)
        if not models:
            print(f"mnemobun: no model suggestions ({error})")
            return
        print(f"mnemobun: models at {endpoint} (set one in the 'model' field):")
        for model in models[:20]:
            print(f"  - {model}")

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

    def feed_tick(self, run) -> str | None:
        """Called by the registered idle task. Feed when the trigger fires (D4).

        ``run`` is the host's IdleTaskRun (kept for signature parity with
        ``dream_tick``; feed keeps its own internal watermark).
        """
        if not self._ensure_store():
            return None
        report = self._provider().feed_tick()
        if report.get("needs_model"):
            return None
        written = int(report.get("written") or 0)
        if written:
            return f"feed extracted {written} new record(s)"
        return None


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
    try:
        ctx.register_idle_task(
            "feed",
            provider.feed_tick,
            interval_hours=1.25,
            min_idle_hours=0.5,
            first_run="defer",
        )
    except Exception as error:
        import logging

        logging.getLogger(__name__).warning(
            "mnemobun: idle-task feed registration unavailable: %s", error
        )
