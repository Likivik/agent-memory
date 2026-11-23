# Code-Quality Pass (P12): all review findings, plus docket → docket

Status: DECIDED 2026-11-22 (Likivik: address all findings; the sleep ruling list is renamed **docket**).
Source: whole-app best-practices review of 97 files / 19.6k lines, 2026-11-22.

## Decisions (closed 2026-11-22)

| # | Question | Decision |
|---|---|---|
| D1 | Naming | The sleep ruling list is the **docket**: proposals are *docketed*, the reasoner *rules the docket* at the existing caps (10 accepts + 5 conflicts + 3 merges). No behavioural change — rename plus docstring truth. |
| D2 | Order | Small safe fixes first (Q4/Q5/Q6), then the two structural refactors (Q1/Q2), plugin de-duplication last (Q3) — each its own PR, full suite as the gate. |
| D3 | Refactor guardrail | Every refactor PR must keep the suite green **without editing assertions to fit new names** — except mechanical identifier renames (docket→docket), which may touch tests. |
| D4 | The Manage split stops at two classes | `Dream` (deterministic half: normalise, settle, co-occur, dedupe, cluster) and `Docket` (drafting + rulings + caps). NOT more pieces; `manage.py` becomes a thin façade re-exporting both so `mem sleep` and callers are untouched. |
| D5 | Hosts split is per-dialect files | `hosts.py` (1,190 lines) → `hosts/` package: `hosts/base.py`, `claude_code.py`, `codex.py`, `hermes.py`, `muse.py`, `specs.py`. `hosts.py` re-exports for back-compat within the repo. |

## Phases (each with acceptance)

### Q-1 — small fixes, one PR (safe, mechanical)

1. `core/context.py::_body` — swallowed read errors now debug-log (`logging.getLogger(__name__).debug`) before returning `""`; test pins the log call.
2. `core/config.py` — hoist `import hashlib, json` from the three method bodies to module top (house style: imports at top, confirmed everywhere else).
3. `mcp/tools.py` — delete the design-doc mapping table from the docstring (it duplicates `DESCRIPTIONS`); keep a one-line pointer to `docs/`.
**Accept:** full suite green; no behavioural diff except the new debug line.

### Q-2 — docket → docket rename, same PR or its own

Mechanical rename: `docket`/`_docket_group_fields`/docstrings/tests → `docket`/`_docket_group_fields`. Public `DreamReport` fields keep their names unless they contain "docket" (they don't).
**Accept:** `grep -ri docket packages tests` returns only the word "docket" in user-facing prose where it means the restaurant kind (none expected); suite green.

### Q-3 — Manage split: `Dream` + `Docket`

`manage.py` (1,038 lines / 47 methods) → `core/dream.py` (deterministic half: `_normalise_dates`, `_settle_weights`, `_add_cooccurrence_links`, `_merge_exact_duplicates`, `_merge_near_duplicate_groups`, `_cluster`, `_prune_empty_groups`) and `core/docket.py` (proposal drafting: `_propose_*`, caps, `decide`, ledger). `Manage` remains as a façade composing both — `mem sleep`, `auto_dream`, and the plugin's `dream_tick` keep working unchanged.
**Accept:** suite green with only identifier-rename test edits; `mem sleep` output identical; `manage.py` reduced to façade + re-exports (<150 lines).

### Q-4 — hosts package split

`executor/agents.py` → `executor/agents/{__init__,base,claude_code,codex,hermes,muse}.py`; `hosts.py` becomes a re-export shim (D5). Per-dialect constants travel with their dialect (e.g. `MEM_TOOL_PATTERN` → the files that use it).
**Accept:** suite green; `grep "from .hosts import"` call sites unchanged; each dialect file <400 lines.

### Q-5 — plugin de-duplication

`hermes-plugin/__init__.py` stops re-implementing prefetch/sync_turn wrappers: `HermesMemoryProvider` (executor package) gains the recall-count tracking + identity/blocked-store handling, plugin module keeps only: sys.path bootstrap, config fields, `register(ctx)`, and thin delegation. Vendor lib rebuilt; live plugin reinstalled.
**Accept:** plugin tests green (theirs updated only for moved identifiers); one live turn still sync_turns; `hermes memory status` available ✓.

## Risks (mitigated)
- **Rename collateral in CI or Nix flake**: the flake builds from pyproject names only — no "docket"/"agent_memory" strings expected; R1's rename already proved the pattern.
- **Docket/Dream split touching standing propagation tests**: those test outcomes, not class boundaries — no edits expected beyond imports.
- **Live plugin swap mid-rename**: Q-5 ends with `scripts/build_plugin.py --out ~/.hermes/plugins/mnemobun` + a restart, same as the P11 swap.

## Out of scope
- CLI `main.py` size (990 lines is naturally flat dispatch — left alone).
- Any behaviour change to caps, standing rules, or the dream pass.
