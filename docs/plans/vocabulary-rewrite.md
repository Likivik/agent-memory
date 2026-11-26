# Plan: vocabulary rewrite

## 1. Vocabulary (read this first)

Six words. Each means exactly one thing. No word may mean two.

| Word | Means | Never means |
|---|---|---|
| **store** | The memory: record files plus the index. Knows nothing about who reads it. | A harness, a process, a model |
| **record** | One memory file in the store. | A row, a hit, a prompt block |
| **writer** | Who authored a record. Stored per record, used for provenance and audits. | A model, a harness, a process |
| **harness** | The thing that embeds mnemobun and owns the prompt: Hermes, Codex, anything later. | A process we launch |
| **driver** | How we reach a harness. `plugin` = it calls us in-process; `cli` = we spawn it and parse stdout. | The harness itself |
| **worker** | Background labour: distill, dream, write jobs. | A harness, a driver |
| **channel** | Where text enters a harness prompt: `system_prompt`, `prompt_prefix`, `file`. | A transport, a driver |
| **reasoner** | The model that thinks for a worker. | The harness, the writer |

One sentence holds the model: **a driver speaks to a harness through its channels; workers write records to the store.**

Rules that follow:

- No host-specific default anywhere. An unset reasoner, channel or driver is an error, never a guess.
- `agent` is retired as a word. It meant three things (a dialect module, a record's author, any model-driven worker) and that is why the code reads badly.
- `host` is retired. It meant both "the thing that embeds us" and "the thing we spawn".

## 2. Where we are

Two cleanup changes are in the working tree, uncommitted:

- `MEMORY.md` and the injection track are deleted (one always-on surface: the pinned block).
- The Claude Code executor dialect is deleted, and an unknown host now raises instead of falling back to Claude.

## 3. Mapping

| Now | Becomes | Notes |
|---|---|---|
| `executor/agents/` | `executor/drivers/` | Modules that launch a process and read its output |
| `ClaudeCodeDialect`, `CodexDialect`, `HermesDialect` | `CliDriver` subclasses | One class per CLI shape |
| `DIALECTS` | `DRIVERS` | Keyed by harness name |
| `HOST_CLAUDE_CODE`, `HOST_CODEX`, `HOST_HERMES`, `HOST_MUSE_CODE` | `HARNESS_*` | Constants name harnesses, not hosts |
| `moments.py` host map | `moments.py` harness map | Same content, `HARNESS_*` keys |
| `hook_entry` `--host` flag | `--harness` flag, no default | A hook with no harness is an error |
| `pin_channel.py` | `channels.py` | `PinChannel` → `Channel`, registry keyed by harness |
| `record.agent` | `record.writer` | On-disk field changes: see §4 |
| `executor` package | stays | It is already the workers' home |
| `Store(agent=...)` | `Store(writer=...)` | Constructor keyword |

## 4. On-disk compatibility

`agent:` is written into every record's frontmatter. Renaming it is a format change, so it needs a migration, not a sweep.

- Read: accept both `writer:` and legacy `agent:`; `writer` wins if both exist.
- Write: always `writer:`.
- Migrate: `mnemobun manage migrate-writer` rewrites legacy files in place, one record per file, provenance preserved, and reports the count.
- A record with neither field is invalid, not defaulted.

Ship read-compat and write-new in R4; ship the migration command in R5; keep read-compat for one release.

## 5. Deletions that ride along

Claude Code is a future harness, not a current one. Nothing about it may remain as a default or as untested code.

- `adapters/setup.py` Claude settings template and its entry in the harness map.
- `adapters/doctor.py:505` Claude-specific check.
- `adapters/hook_entry.py` `CLAUDE_*` response keys: generalize to `response_keys(harness)`, with the Claude shape as data, not as a branch.
- Tests that exist only for Claude: `test_host_encoding.py`, `test_tool_host_postures.py`, and the Claude cases inside `test_host_dialects.py`, `test_write_triggers.py`, `test_judge_hosts.py`, `test_reasoners.py`.
- `tests/system/claude_live.py` and anything that shells out to a `claude` binary.

Dead code is paid for on every refactor. Rebuild it when a second harness is actually on the table; the driver interface is what makes that cheap.

## 6. Increments

Each increment is one commit, tests first where the change has behaviour.

**R1 — glossary lands first.** Add this file's §1 to `docs/design/vocabulary.md` and link it from `README.md`. No code. Reason: the words must exist before the rename, or reviewers argue about them per file.

**R2 — harness constants.** Rename `HOST_*` to `HARNESS_*` across packages and tests, `moments` host map included. Mechanical, no behaviour change. Test: full gate unchanged.

**R3 — driver package.** Move `executor/agents/` to `executor/drivers/`, rename `DIALECTS` → `DRIVERS`, dialects → `*Driver`. Keep the class bodies untouched. Test: gate unchanged; an unknown harness raises.

**R4 — channels.** Rename `pin_channel.py` → `channels.py`, `PinChannel` → `Channel`; registry keyed by harness; `pin_channel.sync` → `channels.deliver`. Test: digest parity across harnesses still holds.

**R5 — writer, data half.** Accept `writer:` on read, write `writer:` on write, reject a record with neither. Add `manage migrate-writer` and a test that a legacy file round-trips with provenance intact.

**R6 — writer, code half.** `record.agent` → `record.writer`, `Store(agent=)` → `Store(writer=)`, audit and access-log columns follow. Test: provenance and audit output name the writer.

**R7 — no defaults.** `--harness` requires a value; `write.reasoner` empty means deterministic-only with a loud refusal (already true); `channels.deliver` refuses an unknown harness. Test: each of the three refuses explicitly.

**R8 — Claude Code removal.** Delete §5's list. Test: gate green with those modules gone; no `claude` string in `packages/`.

## 7. Gate

`uv run --group dev pytest tests/unit/ -q --no-header -p no:cacheprovider`, plus `ruff check`. Green at every commit; a rename that leaves the gate red is not finished.

## 8. Out of scope

- Adding a second harness. That is a driver, written when it is needed.
- The unification items reviewed but not chosen: a single byte-budget helper, a single digest helper, a single atomic-write helper. They are real, they are separate, and they are cheaper after the vocabulary settles.
- Merging `injection`-style floors back in. There is one always-on surface: the pinned block.
