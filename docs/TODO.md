# Follow-ups

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
