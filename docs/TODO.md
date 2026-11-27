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
