# Obsidian Work Skills

This repository is the single source of truth for three Codex skills:

- `obsidian-wiki`: persistent per-repository wiki notes in Obsidian.
- `hypatos-glossary`: persistent Hypatos terminology entries in Obsidian.
- `obsidian-work-tasks`: lightweight personal work-task notes in Obsidian.

The skills keep separate user-facing workflows and helper CLIs, but share the `obsidian_work` Python package for common Obsidian mechanics: configuration, project detection, path confinement, frontmatter handling, redaction, atomic writes, and Markdown section updates.

## Layout

- `skills/obsidian-wiki/`: Codex skill manifest and default config for wiki notes.
- `skills/hypatos-glossary/`: Codex skill manifest and default config for glossary entries.
- `skills/obsidian-work-tasks/`: Codex skill manifest and default config for work tasks.
- `commands/`: Codex prompt wrappers for `/document`, `/glossary`, and `/worktask`.
- `scripts/`: stable helper entrypoints and the wiki MCP server.
- `obsidian_work/`: shared Python core used by both helpers.
- `tests/`: unit tests ported from both source repositories plus shared-core tests.
- `docs/`: maintainer documentation.
- `Taskfile.yml`: build, install, and verification tasks.

## Build And Verify

```bash
task build
task verify
```

The build creates:

```text
dist/obsidian-wiki
dist/hypatos-glossary
dist/obsidian-work-tasks
```

Each package contains its skill manifest, config, helper scripts, shared `obsidian_work` package, command wrapper, and `requirements.txt`.

## Install For Codex

```bash
task install:codex
```

This installs only Codex runtime files:

```text
~/.codex/skills/obsidian-wiki
~/.codex/skills/hypatos-glossary
~/.codex/skills/obsidian-work-tasks
~/.codex/prompts/document.md
~/.codex/prompts/glossary.md
~/.codex/prompts/worktask.md
```

Restart Codex after installing or changing skill manifests.

## Configuration

Preferred project-level config lives under `.codex/`:

```text
.codex/obsidian-wiki.json
.codex/obsidian-glossary.json
.codex/obsidian-work-tasks.json
```

For compatibility, the helpers still read `.agents/*.json` and `.claude/*.json`. `OBSIDIAN_VAULT_PATH` overrides only the vault path.
