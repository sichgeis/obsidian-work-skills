---
name: hypatos-glossary
description: Research and document Hypatos company, product, IT-system, and source-code terminology in an Obsidian glossary. Use when the user asks to add, update, explain, research, or document a glossary entry for a term, phrase, acronym, source-code identifier, data model, service, product concept, business concept, or internal system in the context of Hypatos.
---

# Hypatos Glossary

Use this skill when a user wants a persistent Hypatos glossary entry written into Obsidian. Do not use it when the user explicitly opts out of glossary or Obsidian logging.

## Required Behavior

- Never write glossary notes directly. Use `scripts/obsidian_glossary.py` for scan, read, create, update, and index operations.
- Resolve `scripts/obsidian_glossary.py` relative to this skill directory when the current working directory is not the installed skill directory.
- Run the script from the project being researched, or pass `--project` when the source project needs an explicit override.
- Store all entries under `{vault_path}/{glossary_dir}/`.
- Keep one note per canonical term.
- Before creating a note, always scan the glossary for possible matches.
- If a likely match exists, read it before deciding whether to update or create.
- Update an existing entry when it already covers the canonical term or a clear alias.
- Create a new entry only when no good match exists.
- Update the glossary index after every create or update. The script does this automatically.
- Expect secret redaction to run automatically before content is written.

## Research Workflow

1. Identify the canonical term exactly as the user gave it unless they provided a preferred canonical spelling.
2. Search the active repository for exact and likely variants of the term.
3. Inspect nearby definitions, tests, schemas, API contracts, migrations, configs, docs, and call sites.
4. Determine the term's meaning in Hypatos company, product, IT-system, and source-code context.
5. Scan existing glossary entries for the term and aliases.
6. Read likely matches.
7. Create or update the entry with concise, source-grounded Markdown.
8. End by telling the user which vault-relative glossary path was created or updated.

## Entry Content

Use this structure unless the topic clearly needs a smaller entry:

```markdown
## Meaning
Concise explanation of what the term means at Hypatos.

## Product Context
How the term fits into the product, workflows, users, or business domain.

## Source Code Evidence
Repo-backed findings with file references and short explanations.

## Related Terms
- [[Other Term]]

## Open Questions
Unclear or inferred points that need human confirmation.
```

Prefer evidence over speculation. If the code suggests a meaning but does not prove it, say so under `Open Questions`.

## Configuration

Configuration resolves in this order:

1. `OBSIDIAN_VAULT_PATH` environment variable for `vault_path`
2. `.codex/obsidian-glossary.json` in the active project
3. `.agents/obsidian-glossary.json` in the active project for legacy compatibility
4. `.claude/obsidian-glossary.json` in the active project for legacy compatibility
5. `config.json` in this skill directory

Defaults installed with this skill:

- `vault_path`: `/Users/christian/vault/Hypatos`
- `glossary_dir`: `Glossary`
- `index_file`: `Index.md`
- `default_tags`: `glossary`

## Codex Permission Behavior

When running under Codex, minimize approval prompts:

- Use the installed script path: `/Users/christian/.codex/skills/hypatos-glossary/scripts/obsidian_glossary.py`.
- Use `--content` only for short, simple, single-line content that does not need shell interpolation, command substitution, here-docs, or ANSI-C `$'...'` quoting.
- Use `--content-file` for multiline, quote-heavy, or generated Markdown. Put the temporary file under a sandbox-writable location such as `/private/tmp`, then run a clean helper command like `python /Users/christian/.codex/skills/hypatos-glossary/scripts/obsidian_glossary.py update --path ... --mode ... --content-file /private/tmp/glossary.md`.
- If Codex asks for command approval, allow the prefix `python /Users/christian/.codex/skills/hypatos-glossary/scripts/obsidian_glossary.py` for future runs.
- Codex approvals are command-prefix based, not semantic skill approvals. There is no separate skill-level allowlist.
- Commands wrapped in shell features such as here-docs, `$'...'` strings, command substitutions, redirections, or long `/bin/zsh -lc ...` payloads may not match the durable prefix rule even when the underlying Python script is allowlisted.
- Treat such a rule as trust in this script invocation, not as fine-grained inspection of every internal Python file write or subprocess.

## Slash Command Workflow

The optional `glossary` slash command is a convenience wrapper around this skill. When invoked, treat the command arguments as the glossary term to research for the current repository.

- Use the argument text as the term, for example `accounting_data`.
- Inspect the project enough to document the term accurately before writing.
- Use the standard scan/read/create/update workflow above.
- Do not create a duplicate note when an existing page already covers the term.
- In the final response, include the vault-relative glossary note path that was created or updated.

## Commands

Run the installed script from the project you want to research. Replace `/path/to/hypatos-glossary` with this skill directory when needed:

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py scan --query "accounting_data"
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py scan --query "accounting_data" --limit 5
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py read --path "Glossary/accounting-data.md"
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py create \
  --term "accounting_data" \
  --summary "Canonical accounting data object used by the product workflow." \
  --content-file /private/tmp/accounting-data.md
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py update \
  --path "Glossary/accounting-data.md" \
  --mode replace \
  --section "Source Code Evidence" \
  --content "Updated evidence goes here."
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py update \
  --path "Glossary/accounting-data.md" \
  --mode rewrite \
  --content-file /private/tmp/accounting-data.md
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py index
```

```bash
python /path/to/hypatos-glossary/scripts/obsidian_glossary.py doctor
```

## Notes

- `scan` returns JSON with titles, canonical terms, aliases, tags, and vault-relative paths. Use `--limit` to bound results.
- The script detects the active project from the current working directory and its git root, unless `--project` is provided.
- `read` returns the full Markdown document.
- `create` fails if the term slug already exists.
- `update --mode replace` replaces the named heading section or creates it if missing.
- `update --mode rewrite` replaces the full entry body while preserving frontmatter.
- `doctor` helps diagnose resolved configuration and filesystem access.
- All resolved paths are constrained to the configured vault root.
- Writes are atomic to avoid partial documents.

After creating or updating this skill, restart the coding agent so it can load the updated skill manifest.
