# Rename: agent-memory → mnemobun (P11)

Status: DECIDED 2026-11-22 (Likivik picked the name; availability verified — PyPI free, zero collisions).
Goal: rebrand the fork and its artifacts to **mnemobun** without breaking CI, the Hermes plugin, or the live store.

## Decisions (closed 2026-11-22, pending Likivik go-ahead to execute)

| # | Question | Decision |
|---|---|---|
| D1 | Scope | **Full rename**: GitHub repo, Python distribution names, import package `agent_memory` → `mnemobun`, CLI entry name, docs. Half-renames rot; correct architecture beats effort. |
| D2 | Repo rename | `Likivik/agent-memory` → `Likivik/mnemobun` (GitHub redirects old URLs automatically; `gh repo rename`). |
| D3 | Package layout | `packages/*/src/agent_memory/…` → `packages/*/src/mnemobun/…`; distributions `agent-memory-core` → `mnemobun-core`, etc. Wheel/import names all change together in one PR. |
| D4 | CLI binary | `mem` stays `mem` in v1 (short, already shipped in docs/tests). A `mnemobun` console-script alias added (full name, zero collision). |
| D5 | On-disk store format | **Unchanged** — store layout, config.toml, frontmatter, index.db have no `agent_memory` strings in the data path; the live store (37k records + replay) keeps working with zero migration. |
| D6 | Hermes plugin | Plugin dir `~/.hermes/plugins/agent-memory/` → `~/.hermes/plugins/mnemobun/`; `plugin.yaml` name field updated; vendored lib rebuilt from new package names; `memory.provider: mnemobun` in config. Config key change done AFTER the code rename lands. |
| D7 | Upstream | This is our fork's identity; upstream `tigerless-labs/agent-memory` keeps its name. Future upstream syncs must map names (a one-file `CONTRIBUTING` note records the mapping). |
| D8 | Version | `0.1.0` → `0.2.0` on the rename commit (identity change, minor bump). |

## Phases (each with acceptance)

### R1 — mechanical rename, one PR
sed-style rename across: `pyproject.toml`s (name, deps, scripts), `packages/*/src/agent_memory` → `mnemobun`, all imports, `tests/`, `scripts/build_plugin.py`, `hermes-plugin/`, `docs/`. Mypy/ruff/pytest must pass untouched semantics.
**Accept:** full suite green locally (≥1104 tests); `uv run mnemobun doctor` works; `pip install mnemobun-core` import path verified in a scratch venv.

### R2 — repo rename + CI
`gh repo rename mnemobun`; update CI workflow names; push branches (bookmarks re-push); open the rename PR on the new URL and let CI validate on ubuntu+windows.
**Accept:** PR green; old URLs redirect.

### R3 — live artifacts
Rebuild plugin from renamed tree → `~/.hermes/plugins/mnemobun/`; `hermes config set memory.provider mnemobun`; gateway restart; `hermes memory status` → available ✓ with the live store untouched (D5).
**Accept:** store record count identical pre/post; one real turn sync_turns into the store under the new provider name.

## Risks (mitigated)
- **Hermes plugin name length/charset**: verified plugin dirs accept `[a-z-]` names (graphiti precedent).
- **Provenance archives reference old module paths?** They don't — provenance files store prose + stamps, not imports (verified: archive.py writes text only).
- **Stale agent-memory-store dirname**: store dir name is config (`store_path`), independent of package name; leave as-is or rename later, cosmetic.

## Out of scope
- Store data migration (none needed, D5).
- Renaming `mem` subcommands.
