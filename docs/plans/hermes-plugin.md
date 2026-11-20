# Hermes Memory Plugin (P10)

Status: DECIDED 2026-11-21. Target: latest **released** Hermes (API read from the installed
`agent/memory_provider.py`, hermes-agent 0.0.0 nix build — the exact runtime on this host).

## What the released Hermes gives us (verified from source)

- Plugins ship in `~/.hermes/plugins/memory/<name>/` with `plugin.yaml` (name/description/version)
  and `__init__.py`; activated by `memory.provider: <name>` in config.yaml — ONE external provider.
- `MemoryProvider` ABC lifecycle: `initialize -> system_prompt_block / prefetch / sync_turn per
  turn -> tool dispatch -> shutdown`, plus hooks: `on_turn_start`, `on_session_end`,
  `on_session_switch`, `on_pre_compress` (v2 checkpoint API), `on_delegation`,
  `on_memory_write`, `on_profile_*`.
- Full abstract surface (verified): `name, is_available, initialize(session_id, **kwargs),
  unavailable_reason, system_prompt_block, prefetch(query, session_id), queue_prefetch,
  recall_status -> RecallStatus, sync_turn(user_content, assistant_content, session_id, messages,
  turn_author), get_tool_schemas, handle_tool_call, shutdown, identity_signature, get_config_schema,
  save_config, backup_paths, read_config_fields, write_config_fields`.
- Multiplexing contract: one gateway process serves several profiles; the loader constructs a NEW
  instance per agent and refuses rebinding. Everything binds from `initialize()`'s `hermes_home`.
- Background work must use `spawn_context_thread` (contextvars: profile isolation + secret scope).
- `hermes memory status` reports plugin state; unavailable providers warn once per home.
- Gateway builds a fresh AIAgent per message → `initialize()` runs per message → provider init must
  be cheap (lazy Store connect, no eager index rebuild).

## Decisions (all closed 2026-11-21, Likivik session)

| # | Question | Decision |
|---|---|---|
| D1 | How does the plugin import our engine on a read-only Nix Hermes? | Vendor: the plugin dir carries `lib/` with the built `agent_memory` packages (core + adapters + executor + mcp wheels' payloads); `__init__.py` prepends `lib` to `sys.path` before importing. No Hermes source patches, no Nix env changes. Upgrade = re-copy `lib/`. |
| D2 | Where is the store? | Plugin config field `store_path` (via `get_config_schema`/`read_config_fields`), default `~/.hermes/agent-memory-store`; the seeded store is copied/moved there at activation. `AGENT_MEMORY_STORE` env still honoured (config wins). |
| D3 | Verify labeler | v1: `labeler=None` → `memory_verify` returns evidence + `abstain` (honest, zero deps). Upgrade path (P7): executor endpoint reasoner configured in plugin config; NO host-subprocess reasoner in v1 (fresh-AIAgent-per-message makes nested `hermes chat` calls fragile). |
| D4 | Dream trigger | `on_session_end`: if `Manage(store).due(sessions_since)` → run sleep with `reasoner=None` (deterministic half) in a `spawn_context_thread`; proposals queue for the nightly menu. Reasoner-ruling dreams: later, via executor host config. |
| D5 | sync_turn policy | Raw event per turn (as built), `session:<id>` provenance marker, salience filter skipped (v1 keeps everything — the store's dedup handles noise; salience was a graphiti-specific graph-size concern). |
| D6 | Tool surface | All 13 MCP tools via `get_tool_schemas()`/`handle_tool_call` (catalogue/dispatch passthrough). No renames. |
| D7 | Vector leg | Inherited from store config (`vector_enabled=true` already set on the seeded store); plugin does nothing special. |
| D8 | Rollback | `memory.provider: default` reverts to built-in memory; plugin dir stays installed but inert. Plugin never deletes store data. |

## Non-goals

- Reasoner-ruling dreams in-session (needs stable nested-host story → P7).
- MEMORY.md/USER.md backfill (separate, after plugin lands).
- salience filtering, graphiti episode categories (dead with graphiti).

## Phases (each with acceptance)

### HP1 — plugin skeleton + vendoring
`plugins/memory/agent-memory/{plugin.yaml,__init__.py,lib/}`; `__init__.py` sys.path bootstrap +
`HermesMemoryProvider` subclass; a `scripts/build_plugin.py` in the fork that builds the plugin dir
from the repo (wheels → lib). Install into `~/.hermes/plugins/memory/`, `hermes config set
memory.provider agent-memory`.
**Accept:** `hermes memory status` shows the provider available; a gateway restart logs no load
errors; rollback to `default` works.

### HP2 — provider surface
Implement the full abstract surface mapped onto `HermesMemoryProvider`:
`initialize` (bind store_path from config, lazy Store), `system_prompt_block`, `prefetch`
(byte-budgeted claims + query recall, unchanged), `sync_turn` (raw event + `session:` marker),
`recall_status` (injected line count), `identity_signature` (store path + head commit of the fork),
`unavailable_reason` (store missing / index locked), `shutdown` (close DB).
**Accept:** unit tests with a fake hermes_home: prefetch budget respected per turn, sync_turn
writes exactly one event, initialize is idempotent across 100 rapid calls (fresh-AIAgent-per-message).

### HP3 — tool dispatch
`get_tool_schemas` → `catalogue()`; `handle_tool_call` → `dispatch(store, name, args)` returning
stringified JSON (Hermes contract) with `tool_error`-shaped failures.
**Accept:** a test calls all 13 tools through the provider surface on a fixture store; unknown tool
returns the tool_error shape, not an exception.

### HP4 — dream on session end (D4)
`on_session_end` → due check → deterministic sleep in a context thread; errors logged, never raised
into the turn path. Session counter persisted in `state/`.
**Accept:** unit test: due → sleep runs once (idempotent under repeated session_end); not-due → skip.

### HP5 — live activation + soak
Activate on this host (`memory.provider: agent-memory`), one real session: injection indicator
appears on non-trivial prompts, `memory_verify` abstains-with-evidence, tools callable, store grows
by the session's turns. Soak: 3 days of real sessions, then the P9 import decision.
**Accept:** manual probe list executed; store stats show sync_turn events for the soak sessions.

## Risks (mitigations, not questions)

- **Nix python 3.14 vs our 3.13-targeted code**: vendored code must import under 3.14 — verified by
  HP1's acceptance (import on the host interpreter) before anything else.
- **Fresh AIAgent per message**: all expensive work lazy; the Store's SQLite connections must not be
  cached at module level (multiplexing contract) — bound on the instance only.
- **Two writers** (gateway + CLI `mem`): store_lock already serialises; the plugin never bypasses it.
- **fastembed model download on first query**: model already cached on this host from the backfill;
  `AGENT_MEMORY_OFFLINE=1` set in the plugin env to guarantee no surprise network at query time.

## Out of scope

- P7 evals (endpoint reasoner, held), MEMORY/USER backfill (after), P9 import run (after plugin).
