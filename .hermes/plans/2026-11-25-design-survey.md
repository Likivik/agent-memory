# Design survey: structural unification targets

Date: 2026-11-25 · Companion to `2026-11-25-sync-turn-slug.md`
Every claim below was verified by grep against HEAD of this workspace; nothing is inherited
from earlier notes.

## Verified call-site matrix

| Surface | Sites | Shape |
|---|---|---|
| `store.record(` | 4 | cli/main.py:510 · core/docket.py:304 · executor/hermes_provider.py:159 · mcp/tools.py:296 |
| f-string `name=` | 3 | docket.py:306 · store.py:285 · hermes_provider.py:163 |
| `Store(` construction | 10 sites / 8 files | cli, core (3), adapters, executor, harness (2 files, 3 sites), mcp |
| store-path knowledge | 6 files | plugin, adapters/setup, cli/main, core/config, executor/agents/base, harness/{judge,systems} |
| `os.environ` touched | 33 files / 4 distinct var names | resolution logic, not names, is duplicated |
| `except Exception` | 22 sites / 14 files | including the host boundaries |
| `json.dumps` | 36 files (verified) | every surface serializes its own way |
| `as_dict`/`to_dict`/`_parse_` | 30 defs | parallel renderers |
| `datetime.now` | **1 file** — `core/clock.py` | time is already unified (see "clean") |
| `clock.stamp()` | `%Y%m%dT%H%M%S%f` | valid slug fragment; safe as name material |

## Findings, ranked by leverage

### S1. Write identity is invented at four call sites
Only `sync_turn` broke, but all four producers own their own rules for name, provenance and
uniqueness. `store.py:285` even renames on collision (`{name}-{stamp}`), which means identity
silently changes when two writes land in the same second — a record's name is not stable.
**Fix:** one typed append (`RecordDraft` + `ExternalRef`), store-owned identity, digest-suffixed
names, idempotency key. Folds into the slug plan.

### S7. A provider label the store cannot honour (shipped 2026-11-25)

The live menu holds **263 pairs but only 196 distinct ids: 67 ids are offered by two providers**
(`Nous Portal · anthropic/claude-fable-5.2` and `Standard Compute · anthropic/claude-fable-5.2`).
The panel shows a provider, save keeps only the bare id, so the user's provider choice is
silently coalesced and routing follows the host's own preference. The label promises a
distinction the setting cannot hold.
**Decision (2026-11-25): the setting becomes a `(provider, model)` pair** — see
`2026-11-25-model-identity-pair.md`. Rejected: inline ambiguity markers, which patch a lossy
type with a warning and still cannot say "use Standard Compute".

### S2. No composition root
Ten `Store(...)` constructions and six independent store-path derivations; 18 files read the
environment. Any new knob (today: `MNEMOBUN_STORE`) must be taught to six places, and tests
re-wire each entry point by hand.
**Fix:** `MnemobunRuntime` owning store, settings, clock, reasoner, locks, health; CLI/MCP/doctor/
plugin obtain capabilities from it. Core stays host-free.

### S3. Settings and model resolution can drift
`SETTINGS_KEYS`, `ExecutorConfig`, `effective_settings` and the panel schema are four descriptions
of one thing. Concrete hazards verified now:
- an **empty** model menu skips unknown-model rejection entirely (`if menu and …`) — inventory
  failure silently disables validation; must fail closed
- two providers offering the same bare id (`anthropic/claude-fable-5.2`) are indistinguishable
  after save: labels differ, the stored value does not
- `get_config_schema` builds the whole menu **twice** per request (once for choices, once for the
  default) — 265 models parsed twice on every panel load
**Fix:** one settings registry (path, type, default, validation) + typed model resolution
(`explicit | unset | invalid`), never empty-string conventions. The route is a pair — see
`2026-11-25-model-identity-pair.md`.

### S4. Failure is invisible; errors are strings
23 broad `except Exception`; named errors exist only where history forced them
(`ReasonerUnavailableError`, `SpendRefusedError`, `FieldError`). The slug bug produced a WARNING
line and lost every turn for 2h — no counter, no health field, nothing `doctor` could see.
**Fix:** `Refusal` vs `Invariant` taxonomy, stable codes (`validation | unavailable | busy |
spend-refused | schema-mismatch`), counters in a store `health` section, `doctor` renders them,
host-log fallback when the store is unwritable.

### S5. Serialization has 37 implementations
A field added to `Record` must be threaded through 30 renderers to reach the MCP tools, harness,
doctor and panel.
**Fix:** one `RecordCodec`; surfaces render through it.

### S6. Build provenance is unanswerable
"is the latest version running?" cost a manual hash comparison this session (and the gateway was
in fact stale for hours).
**Fix:** build emits commit + content hashes; plugin reports them; dashboard shows them.

## Checked and clean (do not refactor)
- **Time**: `datetime.now` appears only in `core/clock.py`. Earlier notes claiming nine files were
  wrong — verified by grep.
- **Settings I/O**: `effective_settings`/`apply_settings` single implementation in `core.settings`.
- **`slugify`**: one correct implementation; the bug is a call site that bypasses it.
- **Store path resolution**: one function; issue #18 covers the UX, not the structure.

## Ranked vertical slices

1. **Typed writes + idempotency** (S1) — fixes the live bug, closes the class.
2. **Composition root** (S2) — unblocks every later knob.
3. **Settings registry + model resolution** (S3) — three real hazards listed above.
4. **Jobs, health, error codes** (S4).
5. **Serialization codec** (S5) — do when next touching MCP.
6. **Packaging provenance** (S6).

## Decisions
- DECIDED 2026-11-25: slice 1 only on the current go; slices 2-6 need a separate explicit go.
- DECIDED 2026-11-25: all verification stays offline (temp stores, fake host); no live feeding,
  paid calls, deploys or restarts without approval.
