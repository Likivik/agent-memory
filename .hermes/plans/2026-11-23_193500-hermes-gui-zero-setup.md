# Hermes Plug-In-And-Go Memory: Zero-Setup Models, GUI Settings, Spend Guard

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Install the mnemobun plugin into Hermes, set nothing (or one GUI field), and memory works: distill and dreaming run on a chosen model, spend is projected before every call and hard-capped.

**Architecture:** Keep the existing single brain-config read path (`selection.resolve`). Add (1) model inheritance — with no settings, the memory model defaults to the gateway's own routed model; (2) GUI fields in the `memory:` config section that feed the brain config at plugin registration; (3) a spend guard at the one place every LLM call passes through (the reasoner built by `distiller.distiller`), with projection before spawn and a ledger after.

**Tech Stack:** Python 3.14, existing mnemobun packages (core/executor/adapters/mcp/cli), vendored `pyyaml`, Hermes `config.yaml` + `mnemobun-plugin.json`, no new dependencies.

---

## Decisions (closed questions)

- **DECIDED 2026-11-23 (user ruling): the LLM model is never selected silently.**
  No inheritance from the gateway model, no defaults. Empty config = deterministic-only operation
  plus a loud, single nudge (report line + `memory_doctor` red) telling him to set `memory.model`.
  One field: `memory.model`; optional per-job overrides `memory.distill_model` / `memory.dream_model`.
- **DECIDED 2026-11-23: single field first.** `memory.model` is the primary knob; per-job fields are
  optional overrides that fall back to it. YAGNI: no per-tool model matrix.
- **DECIDED 2026-11-23: spend guard lives at the reasoner choke point.** Every LLM call in mnemobun —
  CLI feed/sleep, plugin `feed_tick`/`dream_tick`, case drafting, `doctor --smoke` — goes through
  `distiller.distiller(executor)` → reasoner `ask()`. Wrapping that reasoner covers CLI and Hermes
  paths identically (the plugin vendors the same lib). Zero exceptions: all other tools
  (recall, sync, record, prefetch, index) are deterministic.
- **DECIDED 2026-11-23: in-house thin layer, not LiteLLM.** The reasoner layer (Host spawn +
  EndpointReasoner HTTP) already exists and is two small classes. LiteLLM adoption means a service +
  database for budget enforcement (their docs: budgets need postgres/Redis to be hard). Escape hatch:
  `EndpointReasoner(endpoint=...)` can point at a LiteLLM proxy later with zero code change. No
  separate issue needed; this plan is the in-house tool.
- **DECIDED 2026-11-23 (user ruling): hard bounds are calls + tokens, not USD.**
  A USD cap is not universally enforceable (billing is at the router; host spawns report no usage).
  Hard, enforced limits = what we control: `memory.max_calls_per_run`, `memory.max_tokens_per_day`
  (input tokens, counted from the prompts we send). USD = soft estimate printed in projections and
  logged in the ledger; used for reporting only, except where a provider returns real usage
  (EndpointReasoner), where it may additionally gate.
- **GUI surface reality:** Hermes activation is `memory.provider: mnemobun` in `config.yaml`; the GUI
  settings editor writes that file. The plugin reads `mnemobun-plugin.json` (store path) and now also
  the `memory:` section of `config.yaml` via the vendored `_load_real_config` YAML reader (already
  proven in P13.4; pyyaml is a dependency). If the GUI shows only known keys, `hermes config set
  memory.model X` and the `memory_setup` MCP tool remain as equivalent surfaces.

## Current state (verified)

- Brain config persists via `mnemobun setup` / `memory_setup` (store `config.json`, read through
  `selection.resolve(store.config.executor, ...)` at `packages/executor/src/mnemobun/executor/selection.py`).
- Plugin: `hermes-plugin/__init__.py` — `register(ctx)` registers the provider + `dream`/`feed` idle
  tasks; config file `mnemobun-plugin.json` at `<HERmes_HOME>/` (`CONFIG_FILENAME` line 48).
- Reasoners: `packages/executor/src/mnemobun/executor/reasoners.py` (`HostReasoner`, `EndpointReasoner`);
  `distiller.distiller(executor)` builds the callable.
- No cost accounting exists anywhere in the repo. `docs/pricing-rate-limits/` holds price data.

---

## Phase 1 — Model inheritance (zero setup)

**Goal:** With no settings at all, LLM work does not run: reports say "no model configured" and tell
him which one field to set. Nothing is ever picked silently.

### Task 1.1: `resolve_model()` inheritance chain

**Files:**
- Create: `packages/executor/src/mnemobun/executor/model_inheritance.py`
- Test: `tests/unit/test_model_inheritance.py`

**Step 1 — failing test:**

```python
def test_explicit_brain_config_wins():
    # store config executor.model = "explicit" -> resolve_model returns "explicit"

def test_gui_field_beats_inheritance():
    # gui = {"model": "gui-model"}, real config model = "gateway-model" -> "gui-model"

def test_nothing_resolves_returns_none_and_flags_needs_model():
    # empty everything -> None + needs_model=True (deterministic-only, loud nudge, no silent pick)
    # NOTE: inheriting the gateway model is explicitly banned (user ruling 2026-11-23)
```

**Step 2 — run, verify FAIL** (`uv run --group dev pytest tests/unit/test_model_inheritance.py -q`).

**Step 3 — implement** `resolve_model(*, brain_model, gui: dict, real_config: dict) -> str | None`
chain: brain → `gui["memory"]["model"]` → `real_config["model"]` / `default_model` (the same keys
`PROVIDER_CONFIG_ALLOWLIST` already copies) → `None`. Pure function, no I/O.

**Step 4 — run, verify PASS. Step 5 — commit.**

### Task 1.2: wire inheritance into `feed_tick`/`dream_tick` and CLI

**Files:**
- Modify: `packages/executor/src/mnemobun/executor/hermes_provider.py` (`feed_tick`, `dream_tick` reasoner build),
  `packages/executor/src/mnemobun/executor/selection.py:25-70`,
  `packages/cli/src/mnemobun/cli/main.py` (`_executor`)
- Test: `tests/unit/test_model_inheritance.py` (extend)

**Behaviour (exact):** `selection.resolve` gains keyword `configured_model: str | None = ""` (the GUI
field). Resolution order: per-run flag > brain config > `configured_model` > **nothing**. There is no
host default. When the model is `None` and the operation needs an LLM: the run returns
`reason="no model configured (deterministic-only); set memory.model"` with zero spawns and the report
carries a `needs_model: true` flag the doctor renders red — never an exception, never a silent pick,
never a spend.

**Acceptance:** `uv run --group dev pytest tests/unit/test_model_inheritance.py -q` green; existing
`tests/unit/test_brain_config.py` stays green (1,115 baseline).

---

## Phase 2 — GUI settings (one field + budget)

**Goal:** `memory.model`, `memory.budget_usd_day`, `memory.budget_usd_month` in `config.yaml` drive the
brain config at plugin registration.

### Task 2.1: `BudgetConfig` in core config

**Files:**
- Modify: `packages/core/src/mnemobun/core/config.py` (next to `UsageConfig`)
- Test: `tests/unit/test_spend_guard.py`

```python
@dataclasses.dataclass
class BudgetConfig:
    max_calls_per_run: float = 40.0     # hard (we control it)
    max_tokens_per_day: float = 2.0e6   # hard input tokens (we count what we send)
    est_usd_per_day: float = 1.0        # soft estimate, reporting only
    est_usd_per_month: float = 10.0     # soft estimate, reporting only
```

`Config.budget: BudgetConfig` serialized in `config.json` like `usage` is. Design tests
(`test_no_magic_numbers_outside_the_config_module`) stay green because all numbers live here.

**Acceptance:** round-trip test + the magic-numbers test green. Commit.

### Task 2.2: plugin reads `memory:` section and syncs brain config

**Files:**
- Modify: `hermes-plugin/__init__.py` (a `_sync_gui_config(store)` helper called from `_ensure_store`),
  `packages/mcp/src/mnemobun/mcp/tools.py` (`memory_setup` gains budget args)
- Test: `tests/unit/test_gui_config.py`

**Behaviour (exact):** at registration the plugin reads `<HERMES_HOME>/config.yaml` with the existing
YAML reader. Keys `memory.model`, `memory.distill_model`, `memory.dream_model`,
`memory.max_calls_per_run`, `memory.max_tokens_per_day` overwrite the matching brain-config fields and
are saved via `Config.save`. Missing keys change nothing. Malformed YAML: log a warning, keep the stored
config, do not raise (registration must never break the gateway). `memory_setup` sets the same fields
from chat; last writer wins.

**Acceptance:** test writes a temp `config.yaml` with `memory.model: probe-model`, calls
`_sync_gui_config`, asserts `store.config.executor.model == "probe-model"`; malformed-YAML test
asserts no exception and unchanged config. Commit.

---

## Phase 3 — Spend guard + projection

**Goal:** Every LLM call is projected before it spawns and hard-capped per run/day/month.

### Task 3.1: projection + ledger (`packages/core/src/mnemobun/core/spend.py`)

**Files:**
- Create: `packages/core/src/mnemobun/core/spend.py`
- Test: `tests/unit/test_spend_guard.py`

```python
@dataclasses.dataclass(frozen=True)
class Projection:
    requests: int
    in_tokens: int
    out_tokens: int
    est_usd: float

def project(messages: int, chars: int, model: str, pricing: Pricing) -> Projection: ...
def record_run(ledger_path, projection, actual: Projection | None) -> None: ...
def window_spend(ledger_path, *, day: bool) -> float: ...
```

Pricing table: load from `docs/pricing-rate-limits/` (a JSON sidecar `pricing.json` created in Task 3.2;
unknown model = refuse to project and treat as `est_usd = max_usd_per_run` — the conservative rule).

### Task 3.2: guard at the choke point

**Files:**
- Modify: `packages/executor/src/mnemobun/executor/distiller.py` (wrap the reasoner returned by
  `distiller()`), `packages/executor/src/mnemobun/executor/reasoners.py`
- Create: `docs/pricing-rate-limits/pricing.json` (prices for the models the router lists)
- Test: `tests/unit/test_spend_guard.py`

**Behaviour (exact) — hard bounds are calls + input tokens; USD is soft (user ruling):**
1. Before the first spawn of a run: `project(...)`; print/return it (`--plan` on CLI, report field on
   plugin). Hard gates: calls above `max_calls_per_run`, or day input-tokens above
   `max_tokens_per_day` (counted from the prompts we send) → refuse.
2. Reservation (under `store_lock`): the run's projected calls + tokens are booked before the first
   request, so concurrent runs cannot jointly exceed the day cap.
3. Refusal message (exact text): `spend refused: <reason>; projected <n> calls / <n> tokens, remaining <n>`.
   The run exits with report `reason="spend refused"` and writes nothing.
4. USD: logged in the ledger as an estimate (chars/4, `pricing.json`); recorded as **actual** only
   where the response carries usage (`EndpointReasoner`). USD never gates on the host path.
5. `doctor` reports calls/tokens/est-USD today + this month from the ledger.

**Acceptance:** tests — (a) projection math on a 100-message batch, (b) refusal over day budget,
(c) reservation blocks a second run, (d) `spend refused` text, (e) unknown model prices at the
conservative maximum. Command: `uv run --group dev pytest tests/unit/test_spend_guard.py -q` green.
Commit.

---

## Phase 4 — Rollout ("it just works")

**Goal:** Fresh install = empty store, deterministic-only, loud "set memory.model" nudge. LLM work
starts only after the user sets a model. No content is ever imported or seeded automatically
(user ruling 2026-11-24: the store starts empty; seeding happens only on an explicit request).

### Task 4.1: end-to-end probe and docs

**Files:**
- Modify: `docs/plans/cli-surface.md` (GUI fields + spend guard section)
- Test: `tests/system/test_auth_smoke.py` pattern (no new paid calls without explicit go)

**Steps:** rebuild plugin (`uv run --group dev python scripts/build_plugin.py`), deploy to
`/var/lib/hermes/.hermes/plugins/mnemobun/`, restart `hermes-gateway.service`, run
`memory_doctor` (expect store + brain + budget report), run one `mnemobun feed --plan` against the
live backlog (expect: requests, tokens, est. USD — **no spawn**). Full suite + ruff + mypy green.

**Acceptance:** `memory_doctor` shows `needs_model: true` and an empty store on a fresh install;
after `memory.model` is set it names the model **and its source**; `--plan` prints a projection and
exits 0 without any LLM call; suite 1,129+ green.

---

## Review fixes (2026-11-24, big-issues review; user-approved)

1. **Config ownership — write-once, never revert (DECIDED 2026-11-24).** The GUI `memory.*` fields are
   imported into the brain config **only when the corresponding brain field is empty** (bootstrap).
   Once set (by any surface), the store config owns the value; restarts never overwrite it. Every
   report (`memory_doctor`, `mnemobun doctor`) prints the effective route **and its source**
   (`gui`, `memory_setup`, `cli`, or `unset`). Files: `hermes-plugin/__init__.py`,
   `packages/adapters/src/mnemobun/adapters/doctor.py`.
2. **Jobs run on the bounded path (DECIDED 2026-11-24).** Unattended work (`feed`, `dream` review)
   uses `EndpointReasoner`: one HTTP request per batch, `max_output_tokens` set, usage taken from the
   response. `HostReasoner` (agent spawn: multi-request, tool calls, opaque usage) is **not used by
   unattended jobs** — `selection.resolve` refuses host for `feed`/`dream` and says so in the report.
   Hard bounds = calls + input tokens; USD soft (see Phase 3).
3. **Trust boundary (DECIDED 2026-11-24).** The extraction prompt treats all turn content (including
   tool output) as untrusted data: no instructions follow from it. The feed spawn runs **without
   tools** and **without `--ignore-rules`** (the `--yolo`+terminal form stays for interactive host
   work only). Files: `packages/executor/src/mnemobun/executor/agents/hermes.py` (a
   `feed`/`extract` invocation profile), `packages/core/src/mnemobun/core/prompts.py`.
4. **Own namespace (DECIDED 2026-11-24).** GUI keys live under `memory.mnemobun.*`
   (`model`, `distill_model`, `dream_model`, `max_calls_per_run`, `max_tokens_per_day`) or in
   `mnemobun-plugin.json`; the shared `memory.*` section is not written to. Until the GUI rendering
   of custom keys is verified, the promised surfaces are: YAML file, chat (`memory_setup`), CLI
   (`mnemobun setup`). A probe test asserts the loader keeps unknown keys round-trip.
5. **Plan self-consistency (DECIDED 2026-11-24).** Phase 3 gating = calls/tokens only; Phase 4 =
   empty store + needs-model nudge. Both fixed above.
6. **Plugin↔store version handshake (DECIDED 2026-11-24).** The store records `schema_version` and
   the writing plugin's version at init; `Database.connect()` / plugin registration refuse loudly on
   mismatch (message: `store version X written by plugin Y; this plugin is Z — run index rebuild /
   migration or start from scratch`). The 2026-11-23 crash class becomes a named, testable error.
   Files: `packages/core/src/mnemobun/core/database.py`, `hermes-plugin/__init__.py`.
7. **Store lifecycle (DECIDED 2026-11-24, user order): start empty, seed only on request.** The
   current store is deleted (2026-11-24); no import/replay/graphiti-seed/feed-input runs until the
   user explicitly asks. Phase 4 probes use an empty store only.

## Risks (with mitigations)

- **Settings drift class (pyyaml missing → silent empty copy).** Mitigation: pyyaml is already a
  dependency (P13.4), and Task 2.2's malformed-YAML test pins the failure behaviour (warn, keep
  stored config).
- **HostReasoner actuals are estimates** (the spawn returns no usage). Mitigation: reservation uses
  worst-case `max_usd_per_run`; the monthly cap is the backstop. Router-side reconciliation
  (NeuralWatt usage API) is a named follow-up, not in scope.
- **Concurrent feed + dream runs.** Mitigation: ledger reservation under `store_lock` (single-flight
  per budget window); a second run sees the reservation and refuses or waits — DECIDED: refuses
  (simpler; the idle scheduler retries at the next interval).
- **GUI shows only known Hermes keys.** Mitigation: the fields are plain `config.yaml` keys;
  `hermes config set memory.model X` and `memory_setup` cover every case the GUI does not show.
- **Unknown future model pricing.** Mitigation: unknown model prices at the conservative maximum
  (`max_usd_per_run`), so the guard errs toward refusing, never toward overspending.

## Out of scope (dated decisions)

- LiteLLM / router reconciliation — DECIDED 2026-11-23: deferred; `endpoint` field is the escape hatch.
- P7 eval sweeps — still held for explicit go (spend rule).
- Per-tool model matrices, cost dashboards, alerts — YAGNI until the ledger shows real numbers.
