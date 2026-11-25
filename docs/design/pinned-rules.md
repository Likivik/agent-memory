# Pinned rules: the always-on floor for standing constraints

Status: design, not implemented. Supersedes the ad-hoc "claims block" in `prefetch`.

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
- Truncation, when it happens, is explicit in the rendered file (a trailing marker naming what was
  dropped). Silent clipping is how a rule disappears while looking present.
- **Stability beats freshness.** A block that changes per turn invalidates the prompt cache, so
  edits happen only when a `pin`/`unpin` proposal is accepted — never on a turn.

## Distillation: proposals, never writes

The mechanism already exists; it needs one new proposal kind.

- `core/access_log.py` records citations → salience is counted, not guessed.
- `core/dream.py` runs offline and emits docket proposals; add `pin` and `unpin`.
  - `pin`: a claim cited ≥ N times across ≥ M sessions, or a user correction that repeats.
  - `unpin`: the least-cited pinned claim when the block is at budget, or a pinned claim whose
    standing became `contradicted` / `superseded`.
- `core/docket.py` applies them only after a ruling. Nothing self-pins; a model may draft, never
  decide.
- **Deltas only.** ACE (arXiv 2510.04618, ICLR 2026) shows monolithic context rewriting collapses
  (18,282 → 122 tokens in one step, accuracy 66.7 → 57.1) and calls the bias toward brevity the
  second failure. Pin, unpin, edit-in-place: never regenerate the block from scratch.
- ExpeL (arXiv 2308.10144) validates the counter model: rules carry importance counts, `ADD` /
  `EDIT` / `UPVOTE` / `DOWNVOTE`, removed at zero, and are injected every episode rather than
  retrieved.

## Host attachment, verified per host

| Host | Surface | Preserved as system message |
|---|---|---|
| Hermes | `system_prompt_block()` → `build_system_prompt()` | yes |
| Claude Code | `--system-prompt-file` (already used, `executor/agents/claude_code.py:42`) | yes |
| Codex | `model_instructions_file` in config, else prepended to the prompt | yes |
| Muse | `--prompt-file`, system prompt prepended to stdin | no — prompt file, not a system message |

Correction to an earlier claim: only Muse lacks a preserved system-message surface. Claude Code,
Codex and Hermes all have one, and the adapters already use theirs for Write negotiation.

## Known failure mode

Naive pinning is not unconditional. The same corpus reports operator impersonation in recent
context defeating it (0% → 17% violation, 10% with provenance hardening), and non-English
constraints decaying worst (+42 points Chinese). Consequences for us:

- pinned text carries an explicit provenance marker (source record, accepted date);
- a pinned rule is re-validated against its record at render time; a rule whose record is gone is
  dropped loudly, not silently;
- the block is never the only defence for a destructive action — tool-level approval stays.

## Non-goals

- No summarisation of the pinned block (summaries drop constraints — that is the whole point).
- No fact storage in `MEMORY.md`/`PINNED.md`; those are rule surfaces with a budget.
- No auto-accept. `pin` is a proposal, exactly like `merge` and `supersede`.
- No per-turn regeneration.

## Test plan

- `test_pinned.py`: render order is deterministic; over-budget truncation is explicit; unflagged
  claims never appear; a pinned claim with `standing=contradicted` is refused.
- `test_system_prompt_block.py`: the plugin returns the rendered block, and returns `""` when no
  claim is pinned (no empty header).
- `test_prefetch.py`: prefetch never returns a pinned claim (they belong to the other channel).
- `test_docket_pin.py`: `pin`/`unpin` proposals require a ruling; `_apply` respects the budget.
- Doctor: `PINNED_OVER_BUDGET`, `PINNED_STALE`, `PINNED_UNREADABLE`.

## Open questions

1. N and M for the `pin` threshold — needs a soak, not a guess.
2. Should the block be per-profile? Two profiles on one store would share rules.
3. Do we expose the block through `memory_get` so the agent can read what it is obeying?
