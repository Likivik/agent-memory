# CLI surface redesign (P13) — plan draft

Status: TALKING PHASE — nothing below is implemented. Execute only on explicit go.
Date: 2026-11-23.

## Goals

- One name per concept; names match the code that implements them.
- Guessable surface: noun groups for subsystems, flat verbs for record ops, meta lane flat.
- Fix the resume fingerprint hole in the import path.

## Agreed decisions

0. **`hosts/` package becomes `agents/` right away** (not cosmetic-deferred) —
   user-facing word is "agent"; `mnemobun setup` is the provisioning command.
   README section "mnemobun in plain words" added (feeding / review / borrowed
   agent / docket-case-execution vocabulary).

1. **`context` (prefetch) command is deleted.** Its only caller is the plugin, which
   uses the Python API (`HermesMemoryProvider.prefetch`) directly. No hidden aliases.
2. **Import family unified:** `import <format> <path> [--force] [--batch-id ID]`.
   Adapters: `mnemobun` (own backup, exact restore), `hermes` (state.db),
   future `graphiti` / `claude`. `replay`/`restore`/`ingest` names retire.
   `export --out backup.json` stays the inverse (own format only).
3. **Resume fingerprint (hard requirement fix):** the import watermark stores a
   source fingerprint (schema + turn count + first/last timestamps). On resume,
   mismatch refuses and points at `--force` or a fresh `--batch-id`.
   Idempotent skip-by-name stays as the second line of defence.
4. **Index group:** `index sync` (incremental catch-up, was half of `inspect`) and
   `index rebuild` (full rebuild from scratch, was `rebuild`).
5. **`doctor` is the one health entry** (meta lane, read-only, never writes):
   `doctor` = all checks, `doctor store`, `doctor host --host X`.
   Absorbs `inspect`'s health report and the old `doctor`.
6. **`gc` is safe by default:** bare `gc` prints what it would delete;
   `gc --yes` applies (destructive-verb convention).
7. **Import/export stay flat** (meta lane).
8. **Memory ops stay flat verbs** acting on records: `record`, `read`, `correct`,
   `supersede`, `merge`, `delete`, `trace`, `feedback`, `search` (was `recall`).
9. **Pipeline nouns:** `dream run` (was `sleep`), `dream status` (was `dream-status`),
   `dream worker --claim X` (was `dream-worker`); `distill` stays (machinery,
   exposed for cron/hooks); `writes list/show/retry/cancel/gc` (was `jobs`).
10. Renames land with the old names kept as deprecated aliases for one release
    (additive first, hide aliases later).

## Open questions (pending your ruling)

- **Q1: RESOLVED — judicial, capped:** `docket` (the list) + `case` (the item) +
  `decide` (the verb). Verbs stay standard (list/show/accept/reject).
- **Q2: RESOLVED — `mnemobun setup`** (writes: borrowed agent, model, store path)
  + read-only `mnemobun doctor`. No `host` group in the user surface;
  `hosts/` becomes `agents/` right away (decision 0).
- **Q3: RESOLVED — `jobs`** (approved 2026-11-23). The write queue is the standard
  job/worker pattern: one order = one job, worker claims (lease), executes,
  reports outcome (done/failed/erroled), failed jobs retry. No fancy vocabulary
  below `decide`; the code name `WriteJobs` already matches.

## Feed trigger (approved direction: activity-based, not wall-clock)

Content-based triggers found in research (beyond the settle/cadence signals):
- **Generative Agents (Park 2023): importance-threshold gate** — reflection fires
  when the summed importance of recent events crosses a threshold (150 in their
  1–10 scale ≈ 15–20 notable events); emergent cadence 2–3×/day. Not a timer.
  MicroVerse 2026 sensitivity sweep (40/80/150): lower thresholds fire earlier
  and more often; direction of change preserved.
- **MemGPT: memory-pressure** — flush at ~70% context window, hard at 100%.
- **MemoryOS: heat/popularity** — topic temperature above a threshold.
- **Evidence floor** (practitioner guidance): don't consolidate before ~50
  high-salience episodes exist — early reflections over-generalize thin evidence.
- Honest gap: no controlled study compares threshold vs scheduled vs inline
  triggers head-to-head (open question).

mnemobun design (updated):
- **Primary: quiet-period gap** — process only complete batches (no new messages
  for a gap; ~30 min is LangMem's chat-app number, tune per workload). Purpose is
  batch COMPLETENESS, not frequency.
- **Gate on accumulated importance:** fire only when the unprocessed backlog's
  total importance clears a threshold (Park: sum ≥ 150 on 1–10 scores).
  CORRECTION: record `weight` is NOT importance — it starts at 1.0 and tracks
  usage/attention (boost/penalize, access-driven). For an unprocessed backlog
  the sum ≈ turn count. The Park gate therefore needs the feed extraction to
  rate importance 1–10 per record at write time — one extra number in the same
  LLM call, then stored on the record.
  CHICKEN-AND-EGG (his catch): the LLM score can't trigger its own run. Fix —
  two-stage scoring, matching Park's own "score at perception time": cheap
  deterministic turn scores as messages arrive (user-vs-tool-noise, length,
  novelty vs store via BM25) gate the FEED; the LLM's write-time importance
  then gates REVIEW. Research support: HIM (importance gating at write,
  ablated on LoCoMo), MementoGUI (learned write-salience with threshold gate),
  MemoryBank (no write-time score — the clean counter-case), and the
  write-vs-usage tradeoff critique (Mahendrakar 2026: write scores are frozen
  predictions; pair with usage — our `weight` — for the two-ended tradeoff).
- **Evidence floor + hard backstop:** skip trivial backlogs; force-feed after
  ~50 turns / ~2 h so a never-quiet stream still feeds.

## Two-signal memory scores (2A, direction approved: "sounds like a good idea to try")

- **`importance`** (new field): 1–10, rated by the feed LLM at write time, frozen.
  Answers "is this worth reviewing?" — gates the nightly review working region.
- **`usage`** (renamed from `weight`, his ruling 2026-11-23): usage/attention —
  rises on reads, decays on idleness, `feedback --boost/--penalize` adjusts.
  Answers "is this worth recalling?" — stays in the recall ranking. With the
  store reset the rename is code + config (`weight.initial`) + docs only —
  the fresh seed writes `usage` directly, no data migration.
- Recall ranking becomes f(recency, relevance, importance, usage).

## Perception scores (feed trigger, 2A formalized)

Cheap deterministic per-turn signal, computed at `sync_turn` time (no LLM, free):
1. user-text vs tool-noise (tool output alone ≈ 0),
2. length signal (diminishing returns past a few hundred words),
3. novelty vs store (BM25 hit strength: already-known facts score lower),
4. repetition in the local window (exact/near-dup in last X messages ≈ 0 —
   catches loops and re-asks).

Honest take on the dedup markers he asked about:
- **exact hash** — only verbatim repeats; near-useless for chat prose; fine for
  identical tool-spam filtering.
- **repeatedness vs last X messages** — good noise/loop filter, cheap; that is a
  NOVELTY signal, not an importance signal.
- **BM25 vs store** — free (index exists); use to CLASSIFY (new note vs
  reinforce existing), not to gate: a re-mentioned fact is reinforcement, not noise.
- **vector similarity** — best paraphrase detection, but costs a network/model
  call per turn and the live store runs vector-off; leave it to review
  (merge/dedup cases), out of the hot path.

Accumulate the per-turn signal on the session watermark mark (`Mark.signal`);
feed fires when signal crosses threshold.

## Trigger = signal + token budget + quiet (2B)

Time/turns dropped as primary. Final rule:
- **fire** when (signal ≥ threshold) AND (batch quiet/complete),
- **force-fire** when unprocessed backlog ≈ the feed prompt's token budget
  (MemGPT memory-pressure precedent at ~70% of window; our prefetch is already
  byte-budgeted, same idea),
- **review** likewise: working region sized to the review budget; oversized
  regions split and consolidated hierarchically.

## Large-history review — PENDING RESEARCH (2.1)

Marked for later thought: region selection policy, split sizes, hierarchical
consolidation depth, citation bookkeeping.

Review never sees the whole store. The working region (Auto-Dreamer's design,
and ours already has the parts): records written since the last review
(watermark) + records actually used (access log, incl. D6 synthetic entries).
Imports stream in batches (batch_records=2000 + resume watermark), docket caps
(10 accepts/5 conflicts/3 merges per sleep) bound output, and consolidation is
hierarchical (insights cite source records; later passes consolidate insights).

## LLM-source verification (2026-11-23, grep-hard)

- `core/` and `adapters/` contain ZERO LLM calls. The only model output path is
  `executor/reasoners.py`, with exactly two topologies: `HostReasoner` (spawns
  the borrowed agent) and `EndpointReasoner` (explicit OpenAI-shaped HTTP call,
  credentials via `API_KEY_ENV`/`BASE_URL_ENV` + model + base_url).
- Embeddings are separate (fastembed ONNX or HttpEmbedder) — vectors, not LLM.
- **The live plugin passes `reasoner=None`** — it has never called an LLM.
  Everything in the live store (37k seed + replays) is deterministic import.
  Feed and case-drafting are therefore UNWIRED live today (same gap as the feed
  trigger) — queued work, not silent LLM use.
- Unit tests use stub reasoners; real-LLM behavior is covered only by
  `tests/system/test_live_claude_native_manage.py` (`requires_live_claude`
  gate, real `claude` via HostReasoner).

## Brain configuration re-think (his "this needs re-thinking") — VERDICT

Model/provider is currently set in FOUR places (BINARIES per-host defaults,
HostSpec from executor config, `--reason-host/--reason-model` flags,
EndpointReasoner model+base_url+credentials). **One brain config wins** (vs
derive-from-host, flags-only, env-only): reproducibility — every memory
judgment names the model that made it. `mnemobun setup` writes agent + model +
provider + endpoint once; feed, review and jobs read it; flags override per
run only. **Plugin-first:** the brain config lives in `mnemobun-plugin.json`
and is settable/verifiable from chat via MCP tools `memory_setup` /
`memory_doctor`; the CLI `mnemobun setup`/`doctor` are the terminal twins.

Auth verdict: "do nothing, just verify" — credentials are profile-aware and
global-root in Hermes (evidence from source); run the spawn smoke test to
prove it; copy the credential subset into the sandbox profile only if it
fails. Verify fixes "can we call"; brain config fixes "who answers".

## Subprocess profile hardening (looked at 2026-11-23, code read)

What `_isolated_hermes_environment` does today: ephemeral profile under the real
data root's `profiles/` (reuses installed runtime/deps on purpose), config.yaml
seeds only `mcp_servers` (toolset-wrapped) + optional security flag. Findings:
1. **Prefetch does NOT run in the subprocess** (plugin not loaded in the fresh
   profile) — by design the prompt carries the working set and the worker reads
   via `mem:` MCP tools. Policy: keep, document, and add a test asserting it.
2. **Auth/provider wiring is unverified** — where the spawned agent gets LLM
   credentials from (env vs profile auth) is not asserted anywhere. Add a
   spawn smoke test (also surfaces in `doctor host`).
3. **Settings drift:** the isolated config does not inherit provider-relevant
   user settings (custom endpoints/base URLs). Seed an explicit allowlist from
   the real profile config instead of an empty config.
4. **Temp profile cleanup** — VERIFIED: `finally: shutil.rmtree(home)` removes
   the temp profile after each run. No leak. (Dropped as a gap.)
5. Timeout/kill hygiene and answer-file handling to be covered by tests.

## Command map (final)

- Records: `record · read · correct · supersede · merge · delete · trace · feedback · search`
  (flat verbs on records, per the lane test)
- Data: `import <format> <path> [--force] [--batch-id] · export · migrate`
- Index: `index sync · index rebuild`
- Court: `docket` (list of cases) · `case show · case decide X --accept/--reject`
  · `dream run/status/worker · distill · jobs list/show/retry/cancel/gc`
- Brain: `setup` (writes: borrowed agent, model, provider, endpoint)
  · `doctor [store]` (read-only checks; absorbs inspect's report)
- Meta: `gc [--yes] (dry-run default) · cron install/status/remove · skill`
- DELETED: `context` (prefetch is internal API), `rebuild`/`inspect` (→ index),
  `proposals`/`decide` (→ docket/case), `jobs` keeps its name, `host *` (→ setup),
  `writ/execution/enforcement` candidates (→ jobs). Old names stay as deprecated
  aliases one release.

## Roles (the pipeline)

- **Feeding** (`distill`): raw messages → notes. Triggered by the perception
  signal + token budget + quiet gap (see above). Only ADDS notes.
- **Review** (`dream run`): nightly over the working region — merges, fades,
  files cases when unsure. Changes/deletes, so it asks first.
- **Case**: one suggested change awaiting a ruling. `case decide` signs the
  order (records the judgment; effects follow).
- **Dream worker --claim X**: executes an accepted case via real host tool
  calls; claim = lease so two workers never double-execute.
- **Jobs**: the queue every write flows through (job + outcome + trace);
  retry/cancel/gc. Standard job/worker pattern.

## Store reset (approved 2026-11-23) — kills issues 1 & 2

Drop both stores (`~/.hermes/mnemobun-store/` + stale `~/.hermes/agent-memory-store/`)
and re-seed fresh after the code work lands. Safe because everything in them is
DERIVED: Graphiti export (Nov 16, `~/.hermes/memory-export/`) + `state.db` turns
+ deterministic passes. The live plugin wrote nothing unique (`reasoner=None`,
`sync_turn` never extracts). Only synthetic access entries and dream reports
exist beyond the sources — both regenerate.

Rules:
- **Backup first**: one tar of both store dirs before any delete (cheap insurance).
- **Timing: at P13 execution start, not now** — dropping mid-work leaves the live
  provider empty until re-seed; re-seed runs the same day (~2 min after the
  earlier perf work).
- Fresh seed writes the NEW schema (`usage` field) and NEW record names from
  day one → no old-name debt, no 37k-file migration.

## Major-issue fixes (review 2026-11-23)

1. Old-name duplication → SOLVED by the store reset above (content-hash dedupe
   kept as a safety net in the import path anyway).
2. Deploy-order gate (kept, shrunk): every release that touches store code =
   rebuild plugin -> restart gateway -> `doctor store` -> one live turn ->
   verify. No 37k-file migration anymore (fresh seed writes `usage` directly;
   the `weight`->`usage` rename is code+config+docs only).
3. Feed input source (DECIDED): feed reads Hermes `state.db` via the existing
   `HermesSource`; perception scores computed on the read; NO private message
   buffer is created (no second copy of conversations).
4. Decide -> job handoff (DECIDED): `case decide --accept` ENQUEUES a job;
   workers claim JOBS, never cases. The queue is the single execute path.
5. Auth = BLOCKER-until-smoke-test (not a settled decision): every LLM path
   waits on the spawn smoke test proving credentials reach the sandbox profile.
   Copy-credentials fallback only if the test fails.
Minor (now formalized): the perception signal is DERIVED from the watermark
backlog at read time (crash-safe, no separate accumulator to reset).

## Phases (when executed)

- P13.0: DONE 2026-11-23 (backups in ~/.hermes/backups/).
- P13.1: command regroup + renames (docket/case/decide, index, setup, jobs,
  search) + deprecated aliases + help rewrite. hosts/ → agents/ rename.
  SHIP AS ITS OWN PR (independent of P13.4/P13.5).
- P13.2: import fingerprint check in the watermark + `import <format>` unified
  entry (`mnemobun`/`hermes` adapters; replay/restore/ingest retire).
- P13.3: `gc` dry-run default; `context` command deletion; `inspect` report
  half → `doctor`.
- P13.4: brain config (plugin json + memory_setup/memory_doctor MCP tools +
  CLI twins) + spawn smoke test (AUTH BLOCKER) + subprocess hardening items.
  SHIP AS ITS OWN PR.
- P13.5: importance field + perception scores + new trigger (signal + token
  budget + quiet) + feed idle task wiring + `weight` → `usage` (code/config).
  Depends on P13.4 (brain config) — SHIP AS ITS OWN PR.
- P13.6: re-seed both sources into the fresh store, rebuild plugin, restart
  gateway, verify (deploy gate from fix #2), docs pass, suite green.

## Open research (later)

- Large-history review: region selection policy, split sizes, consolidation
  depth (2.1).
- Trigger research gap: no controlled threshold-vs-scheduled comparison exists
  — keep the option to A/B our gate against the backstop once live.
