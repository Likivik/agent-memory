# TDD plan: pinned rules

Implements [Pinned rules](../design/pinned-rules.md). Every increment is **test first**: write the
test, watch it fail for the stated reason, then the smallest implementation that passes.

Gate for every increment:

```
uv run --group dev pytest tests/unit/ -q --no-header -p no:cacheprovider
uv run --group dev ruff check
```

Baseline today: 1126 passed, 3 skipped. One increment per commit.

## P1 — Render the block

**RED** `tests/unit/test_pinned.py`:

| Test | Asserts |
|---|---|
| `test_only_flagged_claims_are_rendered` | a `pinned: true` claim appears; a fact and an event never do |
| `test_order_is_pin_order_then_name` | explicit `pin_order` first, then alphabetical; separate stores with the same records render identical bytes |
| `test_same_store_renders_same_bytes` | two calls, one digest — the determinism the cache depends on |
| `test_over_budget_truncation_is_explicit` | output ends with a marker naming how many rules were dropped |
| `test_contradicted_pin_is_refused` | `standing=contradicted` (and `superseded`) is excluded and named in the marker |
| `test_missing_record_is_dropped_loudly` | a pinned claim whose record cannot be read raises, never silently skips |
| `test_empty_store_renders_empty_string` | `""`, not a header |

**GREEN** `packages/core/src/mnemobun/core/pinned.py`: `render(store) -> str`, ordering, budget,
truncation marker. Knob `recall.pinned_max_bytes = 2048` in `core/config.py`.

**Watch for**: literal numbers in `pinned.py` — the magic-number guard test wants them in `config.py`.

## P2 — Config surface

**RED** `tests/unit/test_config.py`: the knob exists with default 2048; an unknown `recall.pinned_*`
knob raises `unknown config knob`; settings round-trip exposes the effective value.

**GREEN** `core/settings.py` already reads `RecallConfig` — expected to be free. If not, one branch.

## P3 — Plugin attaches it

**RED** `tests/unit/test_hermes_plugin.py`:

- `test_system_prompt_block_returns_the_pinned_render` — equals `pinned.render(store)`.
- `test_system_prompt_block_is_empty_without_pins` — `""`, and no `"Standing claims:"` header.
- `test_system_prompt_block_survives_a_missing_store` — `""`, no exception (the host must not break).

**GREEN** `hermes-plugin/__init__.py::system_prompt_block` → pinned render + the existing tool blurb.

## P4 — Prefetch stops carrying rules

**RED** `tests/unit/test_hermes_plugin.py`:

- `test_prefetch_never_returns_a_pinned_claim` — even when the query matches its text exactly.
- `test_prefetch_still_returns_unpinned_claims` — the change must not mute recall.
- `test_prefetch_never_returns_events` — already covered, keep it as the regression guard.

**GREEN** one filter in `hermes_provider.prefetch`; delete `_claims_block` and the `_injected`
session map with it.

## P5 — Channel registry

**RED** `tests/unit/test_pin_channel.py`:

| Test | Asserts |
|---|---|
| `test_every_channel_renders_the_same_digest` | hermes, claude-code, codex, muse all receive sha256 of the same block |
| `test_file_channel_replaces_only_its_region` | bytes before and after the `mnemobun:pinned` markers are untouched |
| `test_unchanged_block_is_not_rewritten` | mtime unchanged on a second delivery |
| `test_degraded_channel_reports_unpinned_host` | `preserved=False` sets the flag the doctor reads |
| `test_channel_records_the_digest_it_delivered` | `pin_digest` in `.state` matches the block |
| `test_new_host_needs_no_renderer_change` | a dummy channel registered in the test passes the same parity assertion |

**GREEN** `packages/adapters/src/mnemobun/adapters/pin_channel.py`: `PinChannel(surface, preserved,
refresh, max_bytes)`, `deliver(channel, block, target)`, registry keyed by host name.

## P6 — Pin / unpin proposals

**RED** `tests/unit/test_docket_pin.py`:

- `test_pin_proposal_is_not_applied_without_a_ruling`
- `test_accepting_a_pin_sets_the_flag_and_order`
- `test_pin_is_refused_when_the_block_is_at_budget` — the error names the block size and the cap
- `test_contradicted_pin_raises_an_unpin_proposal`
- `test_unpin_clears_the_flag_without_deleting_the_claim`

**GREEN** `core/reasoning.py` gains `PROPOSAL_PIN` / `PROPOSAL_UNPIN`; `core/docket.py` gains
`_pin` / `_unpin` branches beside `_accept_standing`.

## P7 — Distillation candidates

**RED** `tests/unit/test_dream_pin.py`:

- `test_claim_cited_across_sessions_becomes_a_pin_proposal` — counts come from `access_log`, no LLM
- `test_claim_below_threshold_proposes_nothing`
- `test_candidates_are_deterministic` — same store, same proposal list
- `test_candidate_list_respects_the_cap`
- `test_unpin_candidate_is_the_least_cited_pin` — when at budget

**GREEN** a deterministic scan in `core/dream.py`; thresholds `pin_min_citations`, `pin_min_sessions`
in `ManageConfig` (values decided by soak — start at 3 and 2).

## P8 — Doctor

**RED** `tests/unit/test_doctor_diagnostics.py`: `PINNED_OVER_BUDGET`, `PINNED_STALE`,
`PINNED_UNREADABLE`, `PIN_UNPINNED_HOST`, `PIN_DIGEST_DRIFT` — all advisory (`required=False`),
each with a failing fixture.

**GREEN** `packages/adapters/src/mnemobun/adapters/doctor.py` `_store_checks`.

## P9 — Integration and compatibility

**RED** `tests/unit/test_pinned_integration.py`:

- `test_plugin_block_reaches_the_system_prompt_parts` — fake `hermes_home`, real plugin surface.
- `test_store_without_pinned_fields_reads_clean` — a store written before this feature renders `""`.
- `test_pinned_md_is_exported_and_round_trips` — portability keeps the block identical.

**GREEN** wiring only; no new behaviour.

## Ordering and risk

P1→P2→P3 is the shippable spine: after P3 the rules already ride the system prompt. P4 removes the
old channel and must land in the same commit series, or claims go out twice. P5 and P6 are
independent of each other; P7 depends on P6. P8 last, once the codes it reports actually exist.

Risk to watch: P3 changes what every user sees in their system prompt on the next gateway restart —
the block must be empty until someone pins a claim.
