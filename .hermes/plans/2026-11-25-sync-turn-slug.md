# Plan: record identity and model route

Date: 2026-11-25 · Status: ready to build · One plan (pair work = Part B; previously a separate file)
Facts: `2026-11-25-verification-report.md` (35 checks, re-derived today). Folded: review passes 1–3.

## 1. What is broken (measured)

- Real traffic: `sync_turn failed: name: must be a kebab-case slug` / `… exceeds slug_max_length` —
  turns lost as warnings, for hours, invisibly.
- Live menu: 263 (provider, model) pairs, 196 distinct ids, **67 ids offered by two providers**;
  save keeps only the bare id, so the visible provider is discarded.
- Menu drifted 264 → 263 pairs in one afternoon: picks expire.
- `_model_menu` swallows exceptions to `[]` and `save_config` uses `if menu and …`: the panel
  silently degrades to a free-text box and then accepts anything.

## 2. Verified constraints (do not re-litigate)

`MemoryRecord` has no `id` (name is the key) · ADD_ONLY renames collisions · `record_many(list[dict])`
is the real door (replay, distill, CLI) · `slugify` + `VALID_SLUG` are correct · `os.replace` is used
per artifact but there is no journal · `complete(…, provider=, model=)` exists on all four llm methods
and both overrides are gated · panel renders `select` for any non-empty `choices`; `boolean` is a
real kind · no widget slots · store has no `config.toml` yet (defaults until first write) · `fields`
is a free-form bag, so additions are additive, not a schema break.

## 3. Structure

```
plugin / CLI / MCP / dream / feed        translate only
        ▼
MemoryWriter · TurnCaptureService · RouteResolver      application policy
        ▼
RecordSpec · Route · DedupeKey                          pure domain
        ▼
StoreWriter                                             adapter: lock, commit, projections
        ▼
filesystem
```
The store never decides policy. One exception is explicit and one is not:
`TurnCaptureService` owns raw-turn capture; `MemoryWriter` **refuses** provenance `turn`.

## 4. Commit model (the big gap today)

One logical write touches four artifacts. Order, under one writer lock:
1. record file — temp write + `os.replace` (already atomic per file)
2. dedupe entry — append to `.state/dedupe.jsonl` + fsync
3. index + projection — same lock, rebuilt from files, never hand-maintained
4. event line — `.state/events.jsonl` (structured: `code`, `at`, safe context; never turn text)

Recovery on open: dedupe entry with no record → drop; record without dedupe entry → re-key from
`ExternalRef` when present, else leave. Fault injection between steps 1–3 is an acceptance test.

Lock semantics (previously unstated): single exclusive writer lock; lock file records pid + start
time; stale after 15 min with a live-check → recovered with a WARN event; readers only ever see
committed state because the index is derived from files under the same lock.

## 5. Part A — identity

- `Slug.of(hint)` = `slugify` + **short digest of the full normalised hint** whenever the hint is
  identity-bearing (host session ids, turn identity). Digest-on-truncation alone is not enough:
  `"Hello World"` and `"hello-world"` collapse at the same length. Never empty.
- Host session id travels in `provenance` as `ExternalRef`; it never becomes the name.
- `DedupeKey = sha256(session_id \x1f user \x1f assistant)[:12]`; `session_id` missing ⇒ the
  current UTC date is used in its place. Byte-identical turn in the same session is **refused**
  (`already recorded: dedupe key '<key>'`) — an intentional semantic, not an accident. Matching key
  ⇒ refuse; different key with a colliding name ⇒ today's rename.
- **The store keeps the full turn.** Verified in code: `body=f"USER: {user}\nASSISTANT: {assistant}"`
  is untruncated; `abstract` (240 chars) is only the retrieval-facing gist. History-in-full is the
  design requirement, so no "gist only" mode and **no consent flag** — the earlier `capture_turns`
  idea was wrong and is dropped.
- **Redaction is out of scope** (2026-11-25): the store persists verbatim; scrubbing belongs to the
  agent/harness that produces the turn (it knows its own credential formats), and any future
  scrubber here would be library-backed, never hand-rolled. Tracked in issue #19.
- Capture was off **by accident**, not by policy: it crashed on the slug bug (section 1).
- Health is advisory: lock-free projection from `.state/events.jsonl`; never takes the writer lock,
  so a lock-contention failure cannot block its own counter. `doctor` prints `sync_failures`.

## 6. Part B — route

- One nested value: `[executor] route = { provider, model }`; old `executor.model` is read once as
  `Route("", model)`. Two flat keys are banned: they allow half-configuration by construction.
- `RouteResolver` states: `Resolved | Unset | Unavailable | Vanished`.
  - save: membership check against the current catalogue; `Unavailable` refuses **that submission
    only** — caps and other fields still save.
  - run: `Unavailable` and `Vanished` refuse with distinct strings. No cached route: a stale route
    is "silently inheriting" by another name.
- Sent as `ctx.llm.complete(..., provider=route.provider, model=route.model)`; trust flags
  `allow_model_override` (already true) and `allow_provider_override` (set at deploy).

## 7. Refusal strings (exact)

`model menu unavailable` · `model pair is not offered by any configured provider: '<provider> · <model>'`
· `no route configured (deterministic-only); set memory.model` ·
`no route configured: '<provider> · <model>' is no longer offered` ·
`already recorded: dedupe key '<key>'`

## 8. Increments (the old 8 phases, regrouped)

1. **Domain.** `Slug.of`, `RecordSpec`, `DedupeKey`, `Route` + adversarial tests.
   *Accept:* `tests/unit/test_slug.py::TestSlugOf` — 8 hostile hints (`20261101_173738_8ba95851`,
   `agent:x:local:dm:local-<64hex>`, Cyrillic, emoji, `...`, `""`, 10 000 chars, `-already-slugged-`)
   all valid and ≤ 80; two distinct short hints get distinct names.
   Plus `tests/unit/test_no_ad_hoc_names.py` — AST scan: any `store.record(...)` passing an f-string
   `name=` fails; allowlist empty. This is the regression fence for the live bug.
2. **Write path.** `StoreWriter` commit order, dedupe index, recovery, lock semantics.
   *Accept:* fault injection between steps 1–3 leaves a recoverable, duplicate-free store; concurrent
   double write of one spec yields one record.
3. **Capture and route.** `TurnCaptureService`, `RouteResolver`, fail-closed save, provider kwarg.
   *Accept:* `tests/unit/test_hermes_provider_sync.py` — a turn lands verbatim (body == the text the
   host passed, `abstract` == first 240 chars) **and its name is a valid slug for all three real
   session-id shapes** (underscored timestamp, profile key with colons, empty → `anon`);
   `sync_failures == 0`;
   menu unavailable ⇒ model save refused, caps saved; spy sees both llm kwargs; vanished pair refuses
   with the exact string.
4. **Surfaces and deploy.** plugin/CLI/MCP adapters, health in `doctor`, compat read, deploy.
   *Accept:* suite 1,099+ green, ruff clean, dashboard 200, store still empty, zero new
   `sync_turn failed`, rollback point after each of: copy, restart, smoke.

## 9. Compatibility

Additive fields on the free-form bag (no rewrite); nested route with back-compat read of
`executor.model`; a store whose schema version is newer than the build is refused, never migrated
down; old plugin config keeps working because defaults are read from the store per request.

## 10. Risks

Digest names are less readable (accepted; `abstract` carries meaning) · the collision check only
holds under the writer lock (test included) · `Unavailable` may fire often on a cold catalogue
(refusal is correct, noise is not: cache the catalogue per process, never the decision) ·
a refused replay of a genuinely repeated message is a deliberate loss of one event.

## 11. Pass 4 — the last big items (verified)

**a) RESOLVED — the host routes by provider (probe, 2026-11-25).** One live probe with
`provider='__nope__'`, `model='deepseek-v4.1-flash'`, `max_tokens=4`:
`AuxiliaryClientUnavailable: Provider '__nope__' is set in config.yaml but no API key was found`.
The bogus provider was resolved **before any model call** → the provider argument is honoured, the
call costs nothing, and the failure mode is a clean pre-network error. Part B is unblocked.
`allow_provider_override` is now `true`. Inference for the plan: an unknown or unauthenticated
slug surfaces as `AuxiliaryClientUnavailable` — map it to `Route.Unavailable`, not to a crash.

**a2) The host's own identity is still the model string.** `config.yaml` carries `model:` and
**no `provider:` key**; the payload's `provider` is derived at run time, and each catalogue entry has
both `slug` (`nous`) and `name` (`Nous Portal`). Consequences, non-negotiable:
- never store the display name; persist `provider_slug` + `model_id`, render `provider_name`;
- before implementing Part B, run one **routing-semantics probe**: whether `ctx.llm(provider=slug,
  model=<full id>)` is honoured, and what `Unavailable` looks like when the slug is unknown.
  Part B is blocked on that probe, not on code.

**b) Spend is already append-only — the reference claim was wrong.** `spend.py` appends JSON lines and
derives `usage()` from them; there is no lost-update window. What remains is a **check-then-append**
race on the cap (two processes may both pass a near-limit check). Keep the existing shape; move the
cap check inside the writer lock. Bounded, not silent.

**c) Read isolation is a rule, not a fence.** Only `replay.py` reads record files directly (verified).
Invariant: the index rename is the commit point; outside `StoreWriter`, nothing reads `records/`.
Guard test mirrors the name scan.

**d) Erasure is now a decision.** Capture is on, full turns verbatim. Retention: keep until manual
purge; a `purge captured turns` command is its own issue. Redaction is the producer's job (issue #19).

**e) Dedupe must not use a wall clock.** The fallback date comes from `store.clock` (injected), so
replay and tests agree. The host supplies no turn ordinal, so the key is
`sha256(session_id \x1f user \x1f assistant)[:12]` with a **10-minute receipt window**, not a
permanent ban on repetition.

**f) Deployment completeness and fingerprint.** Deploy is not done until every consumer process is
restarted (dashboard *and* gateway — a stale gateway held old code for hours today). Schema and
`doctor` report `build = {commit, dirty, content_hash}`; an old plugin must refuse a store whose
config it cannot parse rather than rewrite it.

**g) Composition root stays deferred, with a boundary.** New capture/route code must go through the
new services; legacy surfaces stay adapters; migrating the 10 `Store(...)` sites is a separately
approved increment. Without that line the new architecture becomes optional and decays.

**h) Hygiene folded:** one menu cache per `get_config_schema` call (today it builds 263 pairs twice);
`.state` events carry codes and safe metadata, never turn text.

## 12. Decisions (dated, closed)

- DECIDED 2026-11-25: identity is derived in the store, from typed specs; `name` stays the key.
- DECIDED 2026-11-25: identity-bearing hints always carry a digest; truncation alone is not identity.
- DECIDED 2026-11-25: matching dedupe key refuses; a different key with a colliding name renames.
- DECIDED 2026-11-25: the store keeps full turns (body) verbatim; no gist-only mode, no consent
  flag. Redaction is the producer's job (issue #19); purging is a separate issue.
- DECIDED 2026-11-25: route is one nested value; a half-set route resolves to `Unset`.
- DECIDED 2026-11-25: catalogue unreadable fails closed on the model submission only, and refuses
  at run; no cached route is ever used.
- DECIDED 2026-11-25: health is advisory, lock-free, derived from structured events.
- DECIDED 2026-11-25: on-disk additions are additive extensions on the free-form `fields` bag.
- DECIDED 2026-11-25: deploy and trust-flag changes are a separate increment with rollback points.
- DECIDED 2026-11-25: no paid calls, no live feeding, no deploys without explicit go.
- DECIDED 2026-11-25 (pass 4): store `provider_slug`, never a display name; Part B starts with a
  host routing-semantics probe and is blocked until it answers.
- DECIDED 2026-11-25 (pass 4): captured turns are kept until manual purge; purge command is a
  separate issue.
- DECIDED 2026-11-25 (pass 4): dedupe uses the injected clock and a 10-minute receipt window.
- DECIDED 2026-11-25 (pass 4): index rename is the commit point; no reads of `records/` outside
  `StoreWriter`.
- DECIDED 2026-11-25 (pass 4): deployment includes every consumer restart plus a build fingerprint.
