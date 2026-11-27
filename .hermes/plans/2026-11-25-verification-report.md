# Verification report — every assumption re-derived

Date: 2026-11-25 · Method: fresh greps + in-process probes under the host interpreter.
Nothing here is carried over from earlier notes; three earlier numbers were wrong and are corrected.

## Confirmed (35 checks)

Core identity
- `record.py` enforces kebab (`must be a kebab-case slug`) and length (`exceeds slug_max_length`)
- `MemoryRecord` has **no `id`**; `name: str` is the first field — name is the primary key
- `slugify(text, max_length)` truncates with `[:max_length]`; `VALID_SLUG = ^[a-z0-9]+(-[a-z0-9]+)*$`
- `Store.record(self, **spec: object)` — untyped spec bag
- `store.py` renames ADD_ONLY collisions with `{placed.name}-{clock.stamp()}`
- `merge_exact_duplicate` exists
- `clock.stamp()` = `%Y%m%dT%H%M%S%f` (valid slug material; lowercase `t` is legal)
- `datetime.now` appears in exactly one file: `core/clock.py`

Counts (verified twice, two methods)
- `store.record(` producers: 4 · f-string `name=`: 3 · `except Exception`: 22
- `json.dumps`: **36 files** (earlier note said 37 — wrong)
- renderer defs (`as_dict|to_dict|from_dict|_parse_`): 30
- `Store(` constructions: 10
- `os.environ` touched by **33 files**, of which 18 read an uppercase-named variable

Settings and host surface
- `SETTINGS_KEYS = ("model", "max_calls_per_run", "max_tokens_per_day")` (multi-line)
- `provider` is not a setting yet
- host `agent/plugin_llm.py` has `allow_provider_override` + `allowed_providers` — a provider
  override exists and is gated like the model override
- panel kinds: `secret`, `select` (**implied by any non-empty `choices`**), `boolean`, `integer`,
  `number`, `text` — so `type: text` + `choices` renders as a select (explains the live 265 options)
- plugin: 263 (provider, model) pairs, 196 distinct ids, **67 duplicated across providers**,
  264 choices (empty + pairs), model field keys include `choices`

Live state
- store has 0 records; spend 0
- **store has no `config.toml`** — settings are defaults until the first write (new finding)
- `sync_turn failed` lines exist in the gateway logs (the live bug is real, not theoretical)
- menu drifted 264 → 263 pairs since today's deploy: options are not stable across restarts

## New findings (not in either plan)

1. **Silent fail-open in `_model_menu`.** Any exception (e.g. `hermes_cli` not importable in that
   interpreter) is swallowed to `[]`, and the panel quietly degrades from a 264-option select to a
   free-text field. Reproduced while verifying. This is the S4 class, live in shipped code.
2. **Empty menu disables validation.** `save_config` uses `if menu and …`, so an unavailable menu
   accepts *any* model string — fail-open at the exact seam where the plan wanted fail-closed.
3. **No `config.toml` yet** — any plan text saying "the store config.toml holds X" must allow the
   defaults-until-first-write state.

## Decisions
- DECIDED 2026-11-25: the model menu must fail **closed** — an unavailable inventory refuses the
  save with `model menu unavailable` instead of accepting free text.
- DECIDED 2026-11-25: panel option lists are unstable across restarts; a saved pair is validated
  at run time, never assumed valid because it once existed.
