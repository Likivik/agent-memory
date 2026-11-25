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
MODEL_LABEL_SEP = " \u00b7 "  # display only: "Provider - model"
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

    # -- store path (env or the default dir; the store records everything else) --
    def _resolve_store_path(self, hermes_home: str | None) -> Path:

        env = os.environ.get("MNEMOBUN_STORE")
        if env:
            return Path(env)
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
        self._provider_instance = HermesMemoryProvider(
            store=self._store, reasoner=getattr(self, "_ask", None)
        )
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
    # -- model menu (a read-only peek at the host's own picker list) ---------
    # The panel turns every choice into {value: choice}: labels are display
    # only, so each choice reads "Provider - model" and save_config strips the
    # label back to the bare id ctx.llm needs.
    @staticmethod
    def _model_menu() -> list[tuple[str, str, str]]:
        """(label, provider-slug, model-id) from the host picker; nothing is written."""
        try:
            from hermes_cli.inventory import (
                build_model_options_payload,
                load_picker_context,
            )

            payload = build_model_options_payload(load_picker_context())
        except Exception:
            return []
        pairs: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for entry in payload.get("providers") or []:
            slug = str(entry.get("slug") or "").strip()
            name = str(entry.get("name") or slug).strip()
            if not slug:
                continue
            for model in entry.get("models") or []:
                value = str(model)
                label = f"{name}{MODEL_LABEL_SEP}{value}"
                if label not in seen:
                    seen.add(label)
                    pairs.append((label, slug, value))
        return pairs

    def _labelled_model(self, provider: str, model: str) -> str:
        """The menu label for a saved pair (falls back to "slug - model")."""
        if not model:
            return ""
        for label, slug, value in self._model_menu():
            if slug == provider and value == model:
                return label
        return f"{provider}{MODEL_LABEL_SEP}{model}" if provider else model

    def _effective(self) -> dict:
        """Effective settings straight from the store - the panel shows these."""
        if not self._ensure_store():
            return {}
        return effective_settings(self._store)

    def _model_choices(self) -> list[str]:
        """'' (unset) + labelled menu entries + a saved value the menu lacks."""
        menu = self._model_menu()
        choices = [""]
        for label, _slug, _value in menu:
            if label not in choices:
                choices.append(label)
        effective = self._effective()
        saved_provider = str(effective.get("provider") or "")
        saved_model = str(effective.get("model") or "")
        if saved_model:
            labelled = self._labelled_model(saved_provider, saved_model)
            if labelled and labelled not in choices:
                choices.append(labelled)  # never drop a saved pair the menu lacks
        return choices

    def get_config_schema(self) -> list[dict]:
        effective = self._effective()
        store_path = str(self._resolve_store_path(self._hermes_home))
        fields: list[dict] = [
            {
                "key": "model",
                "type": "text",
                "description": (
                    "LLM model for memory work, picked from the host model menu. "
                    "Never inherited; empty = deterministic-only"
                ),
                "placeholder": "unset - deterministic-only, jobs refuse loudly",
                "default": self._labelled_model(
                    str(effective.get("provider") or ""), str(effective.get("model") or "")
                ),
            },
            {
                "key": "max_calls_per_run",
                "type": "number",
                "description": "Hard cap: LLM calls per run",
                "default": effective.get("max_calls_per_run", 40.0),
            },
            {
                "key": "max_tokens_per_day",
                "type": "number",
                "description": "Hard cap: input tokens per day",
                "default": effective.get("max_tokens_per_day", 2000000.0),
            },
            {
                "key": "store_path",
                "type": "text",
                "description": "Filesystem path of the mnemobun store",
                "default": store_path,
            },
        ]
        choices = self._model_choices()
        if len(choices) > 1:  # a select needs real options; else typing
            fields[0]["choices"] = choices
        return fields

    def save_config(self, values: dict, hermes_home: str) -> None:
        submitted = {
            key: ("" if value is None else value)
            for key, value in values.items()
            if key in SETTINGS_KEYS
        }
        if not self._ensure_store(hermes_home):
            raise ValueError(self._unavailable or "store not found")
        raw_model = str(submitted.get("model") or "").strip()
        if raw_model:
            menu = self._model_menu()
            if not menu:
                # fail closed: an unreadable catalogue must never accept free text
                raise ValueError("model menu unavailable")
            picked = next(
                ((slug, value) for label, slug, value in menu if label == raw_model), None
            )
            if picked is None:
                raise ValueError(
                    "model pair is not offered by any configured provider: "
                    f"{raw_model!r}"
                )
            submitted["provider"], submitted["model"] = picked
        submitted_path = str(values.get("store_path") or "").strip()
        resolved = str(self._resolve_store_path(hermes_home))
        if submitted_path and submitted_path != resolved:
            raise ValueError(
                f"store path is fixed at {resolved}; set MNEMOBUN_STORE to move it"
            )
        if submitted:
            apply_settings(self._store, submitted, actor="gui")

    def read_config_fields(self, hermes_home: str) -> dict:
        effective = self._effective()
        return {
            "values": {
                "model": str(effective.get("model") or ""),
                "max_calls_per_run": effective.get("max_calls_per_run", 40.0),
                "max_tokens_per_day": effective.get("max_tokens_per_day", 2000000.0),
                "store_path": str(self._resolve_store_path(hermes_home)),
            },
            "placeholders": {},
        }

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

    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


provider = AgentMemoryHermesProvider()

def _make_plugin_ask(llm):
    """str->str ask backed by the host's ctx.llm - the recorded pair names the route."""
    from mnemobun.core.errors import ReasonerUnavailableError

    def ask(prompt: str) -> str:
        if not provider._ensure_store():
            raise ReasonerUnavailableError("mnemobun store not found")
        settings = effective_settings(provider._store)
        model = str(settings.get("model") or "").strip()
        slug = str(settings.get("provider") or "").strip()
        if not model or not slug:  # never silently inherit a route
            raise ReasonerUnavailableError(
                "no route configured: record provider and model in the mnemobun panel"
            )
        try:
            result = llm.complete(
                [{"role": "user", "content": prompt}],
                provider=slug,
                model=model,
                purpose="mnemobun",
            )
        except Exception as error:
            raise ReasonerUnavailableError(
                f"plugin LLM failed for {slug}{MODEL_LABEL_SEP}{model}: {error}"
            ) from error
        text = getattr(result, "text", None) or getattr(result, "content", None) or result
        text = str(text)
        if not text.strip():
            raise ReasonerUnavailableError(
                f"plugin LLM returned an empty reply for {model!r}"
            )
        return text

    return ask




def register(ctx) -> None:
    """Loader hook: the released loader calls ``register(ctx)`` before the
    subclass scan and passes a real PluginContext — this is the only way a
    memory plugin reaches host surfaces like ``register_idle_task`` (HP4/D4)."""
    with contextlib.suppress(Exception):
        provider._ask = _make_plugin_ask(ctx.llm)  # host-owned routing/auth/keys
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
