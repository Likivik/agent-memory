# Vocabulary

The words this project uses, and the words it refuses. Read this before reading any other
design note: every other note assumes these meanings.

## The six words

**store** — the memory. Record files plus the index. It knows nothing about who reads it.
*A store is not a harness, a process or a model.*

**record** — one memory file in the store, with a name, a type, a standing and a body.
*A record is not a row, a hit or a prompt block.*

**writer** — who authored a record. Stamped per record; used for provenance and audits.
*A writer is not a model, a harness or a process. The `agent:` field on disk is the retired
spelling of this word.*

**harness** — the thing that embeds mnemobun and owns the prompt: Hermes today, another agent
tomorrow. A harness has **channels**.
*A harness is not a process we launch.*

**driver** — how we reach a harness. `plugin` means the harness calls us in-process; `cli` means
we launch it and parse its stdout.
*A driver is not the harness.*

**worker** — background labour: distill, dream, write jobs. A worker uses a **reasoner** for
thinking and writes records.
*A worker is not a harness or a driver.*

## Two more, for the prompt

**channel** — where text enters a harness prompt: `system_prompt`, `prompt_prefix`, or `file`.
Each channel declares whether it survives compaction, how often it refreshes, and its byte cap.

**reasoner** — the model a worker thinks with. Its selection is always explicit; an empty
reasoner means deterministic-only, never "pick a sensible default".

## The model in one sentence

> A driver speaks to a harness through its channels; workers write records to the store.

## Retired words

**host** — retired. It meant two different things: the thing that embeds us, and the process we
spawn. Use **harness** and **driver**.

**agent** — retired. It meant three different things: a per-process dialect module, a record's
author, and any model-driven worker. Use **driver**, **writer**, and *agent* only in prose about
somebody else's software.

## Rules that follow from the vocabulary

1. No harness-specific default anywhere. An unset reasoner, channel or driver is an error.
2. One always-on surface: the pinned block. Text that must always be present goes there, not into
   a second injected index.
3. A name that could mean two things is a defect, not a convenience.
