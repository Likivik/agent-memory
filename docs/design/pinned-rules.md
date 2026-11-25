# Pinned rules: the always-on floor for standing constraints

Status: implemented (P1-P9). Supersedes the ad-hoc "claims block" in `prefetch`.

## The problem, measured

Standing rules ("never prune containers without approval", "report in Russian") decay when the
harness compacts history. Governance Decay (arXiv 2606.22528) measures it:

- Violation with the policy in full context: **0%**. After one compaction: **30%**, up to **59%**.
- When the constraint survives the summary, violation stays **0%**; when it is dropped, **38%**.
- Repeated compaction: **0% → 78%** across four rounds.
- Soft organisational policy decays ~**8×** harder than hard safety norms (50 vs 6 points).
- Delivery channel decides everything: **+0** when the policy sits in the preserved system
  message, **+50** as a standing user instruction, **+45** as a memory entry, **+33** as tool
  output.

mnemobun today delivers standing claims through `prefetch()`, which the host injects into the
**user message** — the +45/+50 channel that compaction eats. That is the defect this note fixes.

## Decision

Rules get their own track, separate from recall, and are pinned into the system prompt.

1. **A claim becomes a rule by flag, not by type.** Frontmatter `pinned: true` plus `pin_order`.
   Facts stay unflagged and remain recall-only.
2. **The block is a rendered artifact, not a query.** `core/pinned.py` renders flagged claims to
   `PINNED.md` at the store root, deterministic order (`pin_order`, then name), no LLM anywhere.
3. **The host attaches it through `system_prompt_block()`.** `agent/memory_manager.py`
   `build_system_prompt()` joins provider blocks and `agent/system_prompt.py:568` appends them to
   the system prompt parts. Rebuilt each turn, therefore never compacted.
4. **Prefetch stops carrying standing claims.** It returns query recall only. One record, one
   channel.

## Budget

- Research floor: **≈47 tokens per governance constraint**, **<0.5%** of a production compaction
  context, restoring violation to 0%.
- Ten rules therefore cost ~470 tokens. Default `pinned_max_bytes = 2048` (~500 tokens, ≈10
  rules), hard cap; `PINNED_OVER_BUDGET` is a doctor check, not a silent truncation.
- Truncation, when it happens, is explicit: the block ends with a trailing marker counting what was
  dropped, and `PINNED_BUDGET` fails in the doctor. Silent clipping is how a rule disappears while
  looking present.
- **Stability beats freshness.** A block that changes per turn invalidates the prompt cache, so
  edits happen only when a `pin`/`unpin` proposal is accepted — never on a turn.

## Distillation: proposals, never writes

The mechanism already exists; it needs one new proposal kind.

- `core/access_log.py` records citations → salience is counted, not guessed.
- `core/dream.py` runs offline and emits docket proposals; add `pin` and `unpin`.
  - `pin`: a claim cited ≥ `pin_min_citations` times across ≥ `pin_min_queries` distinct queries
    (the access log has no session column; distinct queries is the honest proxy), or a user
    correction that repeats.
  - `unpin`: a pinned claim whose standing became `contested` / `superseded`, or — when the block
    overflows — the least-cited pinned claim.
- `core/docket.py` applies them only after a ruling. Nothing self-pins; a model may draft, never
  decide.
- **Deltas only.** ACE (arXiv 2510.04618, ICLR 2026) shows monolithic context rewriting collapses
  (18,282 → 122 tokens in one step, accuracy 66.7 → 57.1) and calls the bias toward brevity the
  second failure. Pin, unpin, edit-in-place: never regenerate the block from scratch.
- ExpeL (arXiv 2308.10144) validates the counter model: rules carry importance counts, `ADD` /
  `EDIT` / `UPVOTE` / `DOWNVOTE`, removed at zero, and are injected every episode rather than
  retrieved.

## Delivery channels: one renderer, many transports

Pinning is not a Hermes feature. It is a **channel contract**: the store renders one block, and a
per-host transport delivers it to whatever surface that host offers. The bytes are identical across
hosts — same rules, same order, same digest — so a rule cannot mean different things in different
harnesses.

`adapters/pin_channel.py` holds the registry. A channel declares four things:

| Field | Meaning |
|---|---|
| `surface` | where the text goes (`system_block`, `system_prompt_file`, `instructions_file`, `prompt_prefix`) |
| `preserved` | survives compaction (a system message) or not |
| `refresh` | `per_turn` (rebuilt each call) or `per_run` (written before the host starts) |
| `max_bytes` | what this host accepts before it truncates us |

Verified surfaces today:

| Host | Surface | Preserved | Refresh |
|---|---|---|---|
| Hermes | `system_prompt_block()` → `build_system_prompt()` (`agent/system_prompt.py:568`) | yes | per_turn |
| Claude Code | `--system-prompt-file` (`executor/agents/claude_code.py:42`) | yes | per_run |
| Codex | `model_instructions_file`, else prepended to the prompt | yes | per_run |
| Muse | `--prompt-file`, system prompt prepended to stdin | **no** — prompt file, not a system message | per_run |

Invariants:

1. **One render.** `core/pinned.py` produces the block; transports never reformat it, only place it.
2. **Delimited writes.** A file-based channel writes between `<!-- mnemobun:pinned:start -->` and
   `<!-- mnemobun:pinned:end -->`, replacing only that region. The host's own instructions are
   never clobbered.
3. **Digest on every delivery.** The channel records `pin_digest` (sha256 of the block) after each
   write, so a host running stale rules is detectable instead of invisible.
4. **Degraded mode is loud.** A channel with `preserved: false` gets one fallback — the block is
   prepended to the prompt of each run — and the doctor reports `PIN_UNPINNED_HOST` naming the host.
   Silence here is how a rule quietly stops applying.
5. **Deterministic output.** Same store state ⇒ same bytes, so a per_run channel that rewrites an
   unchanged block does not churn the file or the prompt cache.
6. **No host-specific syntax inside the block.** Markdown lines only; each transport adapts the
   wrapper, never the content.

Adding a host is therefore a registry entry plus a test that the same fixture store renders the same
digest through the new channel.

## Known failure mode

Naive pinning is not unconditional. The same corpus reports operator impersonation in recent
context defeating it — 0% → 17% violation, **10% with provenance hardening**. That residual is
acceptable for a reminder layer; it is not acceptable for a safety control, so the split stays:

- pinned text carries an explicit provenance marker (source record, accepted date), which is the
  mitigation that bought the 17% → 10%;
- a pinned rule is re-validated against its record at render time; a rule whose record is gone is
  dropped loudly, not silently;
- the block is never the only defence for a destructive action — tool-level approval stays.

Non-English constraints decay worst (+42 points Chinese), so a rule language other than English
deserves its own soak test before it is trusted.

## Non-goals

- No summarisation of the pinned block (summaries drop constraints — that is the whole point).
- No fact storage in `MEMORY.md`/`PINNED.md`; those are rule surfaces with a budget.
- No auto-accept. `pin` is a proposal, exactly like `merge` and `supersede`.
- No per-turn regeneration.

## Test plan

- `test_pinned.py`: render order is deterministic; over-budget truncation is explicit; unflagged
  claims never appear; a pinned claim with `standing=contested` is refused.
- `test_system_prompt_block.py`: the plugin returns the rendered block, and returns `""` when no
  claim is pinned (no empty header).
- `test_prefetch.py`: prefetch never returns a pinned claim (they belong to the other channel).
- `test_docket_pin.py`: `pin`/`unpin` proposals require a ruling; `_apply` respects the budget.
- `test_pin_channel.py`: every registered channel renders the **same digest** for one fixture store;
  a file channel replaces only its delimited region and leaves surrounding lines byte-identical;
  an unchanged block is not rewritten; a `preserved: false` channel reports `PIN_UNPINNED_HOST`.
- Doctor: `PINNED_OVER_BUDGET`, `PINNED_STALE`, `PINNED_UNREADABLE`, `PIN_UNPINNED_HOST`,
  `PIN_DIGEST_DRIFT`.

## Not wired yet

`adapters/pin_channel.py` is a registry with a digest test. Hermes delivers through
`system_prompt_block()`; Claude Code, Codex and Muse deliver through `pin_channel.sync(store, host,
path)`, which renders and splices the block into their prompt file. The executor does not call
`sync()` yet — that hook is the remaining increment.

## Open questions

1. N and M for the `pin` threshold — needs a soak, not a guess.
2. Should the block be per-profile? Two profiles on one store would share rules.
3. Do we expose the block through `memory_get` so the agent can read what it is obeying?
