# Implementation Notes

## Combined Repository

`obsidian-work-skills` packages three Codex skills from one source repository. The installed skill names remain `obsidian-wiki`, `hypatos-glossary`, and `obsidian-work-tasks` so existing Codex usage and helper paths remain stable.

The repository intentionally no longer builds Claude Code or ForgeCode packages. Future non-Codex variants should be derived from the Codex skill sources rather than maintained as first-class build targets here.

## Shared Core

The `obsidian_work.core` module owns common deterministic Obsidian behavior:

- JSON config loading and deep merging.
- project root and project name detection.
- vault path confinement.
- Markdown frontmatter parse/render.
- `--content` / `--content-file` handling.
- default/project/extra tag normalization.
- secret redaction.
- atomic file writes.
- append/replace/rewrite section helpers.

Domain helpers keep their own `Config` and document dataclasses, CLI parsers, payload shapes, and domain-specific indexes.

## Wiki Domain

`scripts/obsidian_wiki.py` remains the stable wiki CLI. It keeps per-project wiki folders, indexed scan, ticket ID matching, snippets, stale-index checks, reversible archiving, `add-frontmatter`, and doctor diagnostics.

`scripts/obsidian_wiki_mcp.py` remains a typed MCP wrapper over the same wiki domain functions.

## Glossary Domain

`scripts/obsidian_glossary.py` remains the stable glossary CLI. It keeps one note per canonical term, aliases, summaries, source project tracking, glossary scan payloads, and `Glossary/Index.md` regeneration.

## Work Task Domain

`scripts/obsidian_work_tasks.py` is the stable work-task CLI. It keeps one note per task in `Work Tasks/`, lightweight task lifecycle metadata, plain Markdown checklist sections, scan/read/create/update/archive operations, and `Work Tasks/Index.md` regeneration.

## Codex Packaging

`task build` creates `dist/obsidian-wiki`, `dist/hypatos-glossary`, and `dist/obsidian-work-tasks`. `task install:codex` copies those packages into `~/.codex/skills` and installs `/document`, `/glossary`, and `/worktask` prompt wrappers into `~/.codex/prompts`.
