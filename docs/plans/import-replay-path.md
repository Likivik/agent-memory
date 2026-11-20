# Import / Replay Path (P9)

Status: DECIDED 2026-11-20 (Likivik approved direction; order: 7/6/5 done, plugin next, this plan for the import path).
Goal: replay historical conversation logs into the store so it behaves as if accumulated over time.

## Why (closed)

- Cold start: a fresh store is near-useless for weeks; import gives day-one value.
- P7 evals (LongMemEval/MemUse-style) are replayed long histories — no import path, no honest eval.
- Future sources: chat exports, other agents' logs. One driver, many adapters.

## Decisions (all closed 2026-11-20, Likivik session)

| # | Question | Decision |
|---|---|---|
| D1 | Historical stamps | `record_many(specs, import_stamps=False)` — when True, specs may carry `created` and `updated`; validated: stamps must parse ISO-8601 and be ≤ now (no future forgery). Live writes keep system stamps. |
| D2 | Recency ranking | NO ranking change. Import sets `updated` = source timestamp, so existing recency decay operates on true history. `created` = source time. |
| D3 | Standing for imported claims | `accepted` with provenance marker `import-batch:<id>` — the import source is the live memory of record. A `standing_policy="proposed"` option exists for replay-strict replays (opt-in, default accepted). |
| D4 | LLM dreaming on import | **Deterministic half only, one pass at the end.** Sleep's date normalisation, co-occurrence links, exact/near-duplicate grouping run over the full corpus. The reasoner NEVER sees the import: merge/split/conflict proposals stay OPEN and drain through the normal nightly menu at its caps (10 accepts + 5 conflicts + 3 merges per sleep). No import-day LLM bill. Rationale: menu-capped rulings are the design's safety property; mass-ruling 22k claims through a reasoner in one shot breaks decision 4/5. |
| D5 | Imported claims are standing=accepted, so no accept backlog | Follows D3/D4. Only duplicate/cluster proposals queue. |
| D6 | Weight decay protection | Imported records have zero access history; first decay pass would sink them to the floor. Mitigation: seed the access log with one synthetic read entry per imported record, `agent="import"`, at import time. Probe `_settle_weights` behaviour on zero-access records before coding; if it ignores zero-access records, the synthetic entry is skipped (verify, don't assume). |
| D7 | Primary source | Hermes `state.db` messages table (~554k messages, timestamps, session ids) — richest and structured. Session JSONLs as a secondary adapter later. Graphiti export adapter already exists (graphiti_import.py). |
| D8 | Replay granularity | One record per TURN (user+assistant pair), like `sync_turn`. No per-message records. |
| D9 | Embeddings | Vector backfill runs once after import completes (existing sync path). ~200k chunks ≈ 30–60 min one-time on CPU. |

## How dreaming is incorporated (D4, expanded)

The import path runs exactly one deterministic sleep pass after all writes:

1. `_normalise_dates`, `_add_cooccurrence_links`, `_merge_exact_duplicates`, `_merge_near_duplicate_groups`, `_cluster` — all deterministic, all benefit from the historical corpus.
2. `proposals()` drafts merges/splits/conflicts — they are RECORDED, not ruled.
3. The host reasoner never runs during import. The open proposals drain through the normal nightly Dream at the existing caps. This is deliberate: the menu is the safety boundary between deterministic drafting and mutation; mass-import must not bypass it.
4. Imported claims enter `accepted` (D3), so the accept menu is not flooded either.

## Phases (each with acceptance)

### P9.1 — core: import stamps
`record_many(..., import_stamps=False)`; `_known_fields` accepts `created`/`updated` only when the flag is set; validation rejects future stamps with `FieldError("updated", "import stamps cannot be in the future")`.
**Accept:** unit tests — stamp accepted, future stamp rejected, live path still rejects stamps. `uv run pytest tests/unit/test_import_path.py -q`.

### P9.2 — core: weight-decay probe + synthetic access
Probe `_settle_weights` with a zero-access record (read the code first, then one unit test). If decay applies, seed synthetic access entries; else document.
**Accept:** a test proving an imported record's weight after one decay pass is ≥ initial (or documented reason it is exempt).

### P9.3 — adapters: hermes source
`adapters/import_source.py`: `HermesSource(state_db_path)` yields turns (user, assistant, session_id, timestamp) in chronological order, batching by month. Handles: multiple sessions interleaved (sort globally by timestamp), empty/system messages (skip), encoding.
**Accept:** unit test on a synthetic state.db fixture (built in-test via sqlite3): turns in order, correct session ids, skips noise.

### P9.4 — replay driver
`adapters/replay.py`: `replay(store, source, *, standing_policy="accepted", batch_projection=None)` — writes with import stamps + provenance `["import-batch:<id>"]`, one projection per ~monthly chunk, then the single deterministic dream pass (D4), then vector backfill note.
**Accept:** integration test on the synthetic fixture: record count, timestamps preserved, provenance marker present, proposals recorded not ruled.

### P9.5 — real run + docs
Dry-run on one real Hermes session; then full `state.db` replay into a fresh scratch store; report counts, elapsed, store size.
**Accept:** scratch-store report committed to the PR description; no live store touched.

## Risks (with mitigations, not questions)

- **Store size**: ~200k turns ≈ 200–400 MB with provenance archives. Mitigation: body truncation to `abstract_max_chars` for abstracts, full text kept in bodies (accepted); revisit if > 1 GB.
- **Embedding time**: 30–60 min one-time; resumable via manifest (indexer skips already-hashed files).
- **state.db schema drift**: adapter reads only `messages`-table columns verified today; adapter raises a clear error if the schema probe fails.
- **Jitter flake**: upstream `test_backoff_jitter` is flaky (seen in CI 2026-11-20, out of this plan's scope) — track separately.

## Out of scope

- MEMORY.md/USER.md backfill (separate, after plugin).
- Reasoner-ruling replay (rejected, D4).
