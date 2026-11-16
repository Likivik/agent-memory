# Plan: bring this fork up to par with our memory research (v1)

Fork: `Likivik/agent-memory` (upstream `tigerless-labs/agent-memory`, main @ PR #129).
Research base: Trilium *Agent Memory Architecture — research note* (+ §10 addendum), *Hermes Agent
Memory — Design v1.0/1.1*, and the five source reviews (tigerless, Mnemosyne, memharness, lemmalog,
Kyros) in the same folder.

Goal: keep upstream's architecture (Markdown files = source of truth, SQLite = deletable cache,
zero-LLM core, menu-capped Manage reasoner) and add the three things our research says are missing:
a five-state standing machine, an answer-audit read track, and in-process Hermes integration.

Every section ends with the source facts it rests on (verified 2026-11-16, main @ 2648ba02).

---

## P0 — Baseline (before any code)

- Run the upstream suite: `pytest` (180+ test files) and the LoCoMo harness (`packages/harness`).
- Record baseline numbers in `docs/plans/uplift-baseline.md`.
- Keep `upstream` remote pointing at tigerless-labs; work on feature bookmarks.

Acceptance: suite green on NixOS (python 3.14 note: upstream requires 3.11+ for tomllib — fine), baseline
harness numbers recorded.

## P1 — Standing machine (the load-bearing gap)

Upstream state model today: one validity interval per file — `active`/`invalid` derived from
`invalid_at` + `superseded_by` (`core/record.py`: "the interval is the sole stored state"). No proposed /
contested / retracted lifecycle, no support propagation.

New module `packages/core/src/agent_memory/core/standing.py`:

- Five states: `proposed | accepted | contested | retracted | superseded` (lemmalog/cortex semantics,
  see Trilium §10.3). Stored as frontmatter fields on the memory file (`standing`, custom fields are
  already merged by `record.py: frontmatter_fields`) plus an append-only `standing_history` table in
  the SQLite index (`index_db` — the cache is rebuildable, so history must be derivable from files;
  standing lives in frontmatter, history in the index + a side JSONL journal).
- **Transitions are code.** Accept: a claim whose `links` antecedents are all active, no unresolved
  conflict. Contest: a `conflicts_with` link to a live peer (both stay retrievable, rank-penalized).
  Retract: no supported antecedent left, or user rejection. Supersede: existing `_supersede` path.
- **Propagation is DRed-style** (lemmalog): retraction of an antecedent retracts dependents;
  *restoring* the antecedent restores them — unless user-rejected. Contest never propagates.
  `links` already exist as a frontmatter field; propagation walks the link graph via the index.
- **The Manage reasoner may only draft standing proposals** into the existing menu flow — it can never
  set standing directly. Upstream already caps and menus the judged half (`manage.py` docstring); we add
  standing proposals to that menu and keep the deterministic `_apply` path.

Tests: `tests/unit/test_standing.py` (transitions, propagation, restore-with-override), differential
test in the style of `tests/differential_test.rs` (upstream lemmalog analogy): random link graphs,
assert propagation results match a naive re-evaluation.

Verified source facts: `links`/`provenance` are first-class record fields (`record.py: FIELD_ORDER`);
custom frontmatter fields are preserved (`record.py: frontmatter_fields` merges `self.fields`);
`_supersede` exists in `manage.py`; schemas are user-editable TOML in `schemas/` dir
(`config.py: schemas_dirname`), so the new `claim` memory type is a TOML file, not code.

## P2 — Answer-audit read track (`memory_verify`)

New `core/audit.py` + MCP tool `memory_verify(draft, query)`:

1. Retrieve twice: once with `query`, once with the **drafted answer** (VtR result, arXiv:2611.05636 —
   the paper's four query-side routers all failed; verifying the produced answer is what worked).
2. Label the evidence 3-way: `supported | conflicting | unsupported`. Labeler = the configured NLI/host
   reasoner, **outside the standing path** (a label never changes standing; it only advises the caller).
3. Return the verdict + the supporting file names; caller policy: abstain when unsupported.
4. Cap verifications per turn; append every verdict to the access log (`core/access_log.py`).

Verified source facts: `recall.py` supports `as_of` and returns provenance/cited_by on each Hit;
`access_log.py` exists; upstream has no equivalent tool (MCP tool list verified — see P4).

## P3 — In-process Hermes integration (prefetch + sync_turn)

Verified gap: `adapters/moments.py` dialects cover claude-code / codex / muse-code / generic only —
**no Hermes entry**; the upstream Hermes support lives on the reasoner side (`executor/hosts.py:
HOST_HERMES`, `HERMES_TOOLSETS = "terminal"`, native MCP write/manage servers). Injection today is a
byte-prefix of MEMORY.md (`core/injection.py`) — deterministic floor, never a summary.

Two additions:

- `adapters/moments.py`: add `HOST_HERMES` dialect mapping Hermes events to the three moments
  (inject / pause / evict) so the generic hook path works.
- **New MemoryProvider plugin** (`integrations/hermes-provider/`, mirroring upstream's
  `hermes_memory_provider/` layout in Mnemosyne for the interface shape): `prefetch()` = read-track
  recall (BM25+RRF + standing penalty, token budget); `sync_turn()` = enqueue a write job
  (`core/write_jobs.py` already has durable, settled-tracked jobs). This is what gives Hermes
  auto-injection without a tool call — MCP alone cannot do this (design doc §6.5).

Tests: `tests/unit/test_provider_prefetch.py`, `test_provider_sync_turn.py` against a scratch store.

## P4 — Tool surface: expose our seven, keep theirs

Target surface (design doc §7): `memory_save, memory_revise, memory_recall, memory_search,
memory_timeline, memory_forget, memory_stats` + `memory_verify` (P2) = 8. Upstream MCP exposes 9
tools (write/read/manage sessions — `packages/mcp/src/agent_memory/mcp/tools.py`, names verified:
`memory_*` family). Plan: keep upstream tools but add a `toolset` config so a host can subscribe to
the minimal set; map ours onto theirs (`memory_save`→record, `memory_revise`→supersede,
`memory_timeline`→new P1 proof-tree view, `memory_forget`→retract, `memory_search`→raw trace).

## P5 — Migration and seeding

- `core/import_graphiti.py`: read `~/.hermes/memory-export/*.jsonl` (FalkorDB dump) → episodes
  (`event` type, `author: graphiti-import`) + durable facts as `accepted` claims with
  `provenance: ["graphiti:episode-<uuid>"]`.
- Seed MEMORY.md + USER.md curated facts as `accepted` claims; the MEMORY.md byte-prefix injection
  track stays as-is (deterministic floor).

## P6 — Consolidation config (Dream)

- Reasoner: `HOST_HERMES` dialect (upstream default table sets a flash-tier model per host — we pin
  ours in config), caps per kind per sleep already enforced by the Manage menu; keep.
- Verify auto-dream concurrency tests still pass with the standing machine present
  (`tests/unit/test_auto_dream.py`, `test_correction_concurrency.py`).

## P7 — Evals

- Upstream LoCoMo harness as regression (`packages/harness`, `examples/longmemeval.rs` is lemmalog's —
  ours is the Python `harness/driver.py`).
- Our two probes from the research note §8.1/§10.4: constraint-retention across 1 and 5 compaction
  rounds; delivered-vs-used (MemUse, arXiv:2611.01718) — memory delivered but not cited counts as a
  failure.

## P8 — Packaging

- Nix derivation (pure Python + tomllib; optional sqlite-vec / sentence-transformers extras stay
  optional). Add `pkgs/agent-memory` to the host config; wire the provider into Hermes plugins.

---

## Verification appendix (assumptions checked against source, main @ 2648ba02)

| Plan assumption | Check | Result |
|---|---|---|
| `links`/`provenance` are first-class record fields | `record.py` FIELD_ORDER | ✅ |
| Custom frontmatter fields survive round-trips | `record.py: frontmatter_fields` merges `self.fields` | ✅ |
| New memory types are TOML data, not code | `schema.py: SCHEMA_SUFFIX=".toml"`, `config.py: schemas_dirname="schemas"` | ✅ |
| Supersede path exists to hang standing on | `manage.py: _supersede` | ✅ |
| No standing machine today | `record.py`: "the interval is the sole stored state" | ✅ (confirmed gap) |
| No Hermes hook dialect today | `adapters/moments.py` DIALECTS: claude-code/codex/muse-code/generic only | ✅ (confirmed gap) |
| Hermes exists on the reasoner side | `executor/hosts.py: HOST_HERMES`, `HERMES_TOOLSETS="terminal"` | ✅ |
| MCP tool list is the `memory_*` family — 9 tools: `recall, read, record, correct, supersede, delete, trace, merge, feedback` (`tools.py: TOOL_* constants`); `memory_trace` exists → proof-tree timeline extends it; no `stats` tool → add in P4 | `tools.py:234-244` | ✅ (closed) |
| Injection is a MEMORY.md byte-prefix | `core/injection.py` (full read) | ✅ |
| Write jobs are durable/settle-tracked | `core/write_jobs.py`, `adapters/write_drain.py` exist | ✅ (behavior re-verify in P0) |

Open items the plan does not decide: whether `memory_search` over raw traces should read the file tree
directly (their raw-evidence read track) or the index; sleep-reasoner model choice; per-sleep caps.

## Decisions closed 2026-11-16 (defaults — vetoable, otherwise final)

| # | Question | Decision |
|---|---|---|
| 1 | Claim format | Their typed-file system; one new `claim` TOML schema, key = (`subject`), group = `subject`. Atomic claims stay single-subject. |
| 2 | Standing storage | `standing` in file frontmatter (source of truth); `standing_history` in the SQLite index + a `state/standing-journal.jsonl` side file so history survives an index wipe (cache is deletable by design — history must not live only there). |
| 3 | Who creates conflicts_with links | The agent in-turn (`memory_revise`/`memory_record` with an explicit `conflicts` argument) — never auto-detected in v1. NLI auto-detection is deferred; false conflicts are worse than missed ones at our scale. |
| 4 | When proposed → accepted fires | On the next Manage/Dream sleep whose reasoner passes a menu item `accept(claim_id)`; plus immediate accept if a user message confirms it. No silent auto-accept. |
| 5 | Sleep reasoner model + caps | Reasoner = Hermes host dialect (our own model routing), cap = 10 proposals per sleep per kind (matches upstream's cap style), auto_dream on. |
| 6 | `memory_search` raw vs index | Raw file-tree grep (their raw-evidence read track) for L1; index for claims. Index is a cache — raw must never depend on it. |
| 7 | Prefetch budget | 1,500 bytes injection floor (their injection_budget default style) + recall top-5 for provider prefetch; tune after MemUse probe. |
| 8 | P2 audit labeler | Same host reasoner (one dependency), temperature 0, structured output; abstain when the labeler itself errors. |
| 9 | Upstream merge cadence | Rebase monthly or on any upstream release tag; CI must stay green on our main before each rebase. |
| 10 | Coverage gate | New modules ship with ≥90% line coverage (upstream gate is 85; our additions must not lower it). |

With these, the plan has no undecided points: every phase has named files, transitions, caps, and
acceptance tests. Remaining unknowns are empirical (P7 evals), not design questions.
