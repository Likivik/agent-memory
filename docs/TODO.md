# Follow-ups

## Research round 2 follow-ups (2026-11-27)

Evidence: Trilium `SubAqV0Mg9La` (16 papers read in full; per-paper notes in
`~/.hermes/cache/scratch/research-round2/`). Verdict: keep the claim store,
reopen the raw path at recall time.

- Recall raw-evidence fallback: when claim-level evidence is thin, fall back to
  raw session/trajectory search and retry (TrajWiki pattern; claims-only gold
  coverage 0.088 vs 0.610 with trajectories).
- Event ledger + deterministic aggregation for count/state questions
  (TallyMem: +13.8 pts on MINTEval, zero construction model calls).
- Citation lock on the read path: an answer may cite only evidence the reader
  actually opened (Agent Zero Memory; 95.6% LongMemEval).
- Probe the dense leg before enabling or deleting it: Agent Zero grep-only is
  within 1.6 pts of hybrid, but AgentMemBench has dense KV at 0.573 long-range
  recall vs <=0.005 for everything else.
- Retrieval depth per operation class: deep retrieval helps QA, shallow helps
  decisions (Harness the Memory).
- Erase semantics: express deletion as an as-if-deleted view over bi-temporal
  retraction (HEAMS: nobody solves Edit; Erase 0-47%).
- Consider a procedural claim kind (runbook/reuse note): QCR beats full
  trajectory replay by +10.7 pts at 48.9% fewer tokens.
- Pair the standing gate with retrieval-time composition control: write-time
  filters stop direct corruption but composed multi-record attacks pass
  (MemPoison L2 residual causal effect 83.6%).
- Dream consolidation needs deterministic, declared ordering: consolidation
  order alone flips behavior (MemForm), and recency-weighted merging is the
  worst updater tested (ASR 99.3% vs 0.0% batch).
- Retracted/superseded claims must leave the FTS5 search surface: repairability
  depends on cheap semantic delete (MemSecBench: semantic backends repair
  87.6-93.3% vs ID-exact 31.8-35.1%).
- Erasure: as-if-deleted views must span claims AND the raw archive; keep
  write-job contexts small (LinEra fan-in law: 1% forget erases 74.8% of
  session-scope derivatives vs 3.9% with 4-turn windows).
- Time-aware retrieval is mandatory at long tenure (Tenure crossover: evicting
  stores decay 96.3%->72.2%, append-only/graph rise to 100%; unbounded vector
  pools without time-awareness also decay).
- Invest in write quality over retrieval machinery: weak writes cause 24.2% QA
  misses vs 1.6% clean; two-stage curated writer halves errors.
- Evaluate memory intrinsically (claim correctness, standing transitions), not
  only via downstream QA: the two disagree (kappa 0.118).
- Rich benign history is a security asset: ~48 benign sessions collapse attack
  persistence (MemoryDojo RSR 55.66% -> 7.94%).
- Counting/aggregation is the universal weakness (4DMemory best 47.58%):
  reconfirms the event-ledger item above.

## Read policy follow-up

- Evaluate the memory-first reading policy with observed exposure before attributing
  answer changes to bounded Trace or optional Vector candidates.

## Management follow-ups

- Revalidate the duplicate keeper under the same writer lock as T0 invalidation; current
  stale-write detection protects only the record being invalidated.
- Decide explicit confirmation and host-level authorization for permanent GC, import and
  cross-store changes; CLI labels alone do not identify a human.
- Decide preimage retention and recovery guarantees for split and in-place correction,
  including stores outside Git and multi-file Manage failures.
- Decide whether direct link/unlink delta commands, relation audit history and per-operation
  bounds are needed; current correct replaces the complete list.
- Review recovery of interrupted multi-file operations outside Git-backed stores.

## Platform follow-ups

- Render setup/doctor checks as code, status and detail in text mode; the recall-hit line
  renderer prints them as empty `name — abstract · path · score=None` rows on every platform.
- Confirm on a live Codex Windows install which shell runs user hooks and that the rendered
  hook command executes there after the one-time trust review.

## Executor follow-ups

- Add explicit cache breakpoints for endpoints that need them, and a context provider per job.
- Keep the authenticated Hermes/OpenRouter native Write matrix in the release checks; ordinary CI
  exercises the same process, stdio MCP, Store, provenance, Watermark, and fail-closed path with a
  deterministic Host.

## Research round 4 follow-ups (2026-11-27)

Source: 16 papers, arXiv Nov 19-25 2026 (round note `E70BSYFiYQHW`, per-paper notes g8-g23 in
scratch `research-round2/`).

- Claim state: make "what currently holds" vs "what once held" first-class with a current-value
  pointer; TASK Memory (2611.34762) shows 53% of revised-fact answers go stale when both versions
  are stored without one.
- Standing gate as publication gate: multi-source + multi-review + predictive check before
  `accepted`; conserve support counts and claim-to-episode pointers as tested invariants through
  dream (IBM 2611.26361 lost provenance silently twice).
- Recall ranker candidate: per-claim utility posterior (Beta e,n, BRAG 2611.31656) x lexical hit
  weight over the FTS5 surface; robust to 30% wrong labels; no dense leg without a gibberish/
  sanity check (EON 2611.31344).
- Serving policy: prefer no-claim over partial-coverage claim (MetaDecomp: -3.02 pp); verify the
  claim subject key against the query before applying (TASK: locality 64.9 -> 96.9); treat scope
  qualifiers ("only for this exact case") as payload-shape signals (MIMPA 2611.31307).
- Withdrawal: three-level semantics (logical invalidation / physical erasure /
  non-reconstructability), enumerate descendants and test post-restoration behavior
  (survey 2611.26983; FORGETMENOT: all 5 commercial agents leak after deletion).
- Health checks: assert store entity count grows (silent read-only store); verify dream output
  recovers source facts before it replaces sources (MemFolder 2611.26427 verification loop).
- Claim typing: polarity (success / failure, DualPM 2611.33612) and descriptive vs normative
  (Map-vs-Territory 2611.29916: 18% of dependency rules broken on day one); each type gets its own
  standing policy.
- Eval: answer-vs-served-claim consistency (use-time), grounded-rate not accuracy
  (AstronautBench 2611.26910 scoring: +1 grounded / -1 correct-but-ungrounded), paired
  useful/harmful vs no-memory (Leto 2611.33005), and a noise floor (~3 tasks) before believing a
  delta (IBM).

## Research round 5 follow-ups (2026-11-28)

Source: 8 papers, arXiv Nov 25 2026 (round note in Trilium Research parent, per-paper notes
g24-g31 in scratch `research-round2/`).

- Dream evaluation = joint utility (new-claim gain + retention of existing claim behavior), not
  the consolidation objective alone (Tune for Retention 2611.34579: "catastrophic forgetting" was
  a selection artifact; 3-of-9 sampled validation tasks select within 1.4 pp of full sweeps).
- Claim debug procedure (HoMe 2611.34624): per-session commits + diff attribution triad - written?
  / corrupted-or-deleted by which session? / retrieved? Prompt-only tuning regresses; structural
  changes win (0.888 -> 0.916 at -59% tokens).
- Catalog scan index over claim titles/descriptions for enumeration questions (HoMe), beyond
  FTS5 top-k; matches the event-ledger counting idea from round 2.
- Pair-level admission tests for interacting claims (same subject key, order of application
  matters; Skills Fail to Compose 2611.34398: >=90% skills compose at <=7.6% in one call);
  anchored revision = rehearse the original claim when revising.
- Keep oldest sparse per-subject facts with unit age weight (INSPIRE 2611.34708: 14-snapshot
  windows evict defining early links; single-vector summaries degrade one endpoint role).
- Label-free post-hoc utility scoring for claim/episode updates (EATS 2611.33897: ~= GT judge
  65.2 vs 65.1; memory also cut tokens 10.5% by suppressing low-value calls).
- Health additions: 19-turn tenure probe (EvoLink-Bench median disclosure->recall = 19 turns);
  retained != usable (SSA: 97.1% of needed chunks kept, 0% used) - serve-time checks over
  store-presence.
- Judgment rule: when a paper attributes a gain to a mechanism, check the tuning/selection regime
  first (Tune for Retention; HoMe MemPro regression; IBM noise floor).
