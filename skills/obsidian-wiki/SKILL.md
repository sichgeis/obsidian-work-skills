---
name: obsidian-wiki
description: Persist codebase knowledge and documented findings into an Obsidian per-repository wiki. Use when the user asks to document findings, save research, build a long-lived project wiki, create a new wiki note for a topic, or update an existing repository knowledge page in Obsidian.
---

# Obsidian Wiki

Use this skill when a user wants persistent repository knowledge written into the Obsidian wiki. Do not use it when the user says "without wiki logging" or otherwise opts out.

## Required behavior

- Never write wiki notes directly. Use `scripts/obsidian_wiki.py` for scan, read, create, update, archive, and restore operations.
- When an `obsidian-wiki` MCP server is available, prefer its typed tools over shell commands; the MCP server wraps the same deterministic helper behavior.
- Resolve `scripts/obsidian_wiki.py` relative to this skill directory when the current working directory is not the installed skill directory.
- Run the script from the project you want to document, or pass `--project` when you need to override the detected project name.
- Keep wiki pages organized under `{vault_path}/{wiki_dir}/{project-name}/`.
- Detect the project name automatically unless the repository needs an explicit `--project` override.
- Before creating a note, always scan the project wiki folder for possible matches.
- If a likely match exists, read it before deciding whether to update or create.
- Update existing notes automatically when they already cover the topic. Create a new note only when no good match exists.
- Prefer indexed scan results when available. Rebuild the index with `index rebuild` when `index status` or `doctor` reports it as missing or stale.
- Archive stale notes only through explicit `archive apply --path ...`; use `archive candidates` for review, and do not bulk-archive without selected paths.
- Preserve concise, useful Markdown. The body is free-form, so choose headings and structure that fit the topic.
- Created notes get a generated `# Title` heading. If create content already starts with the same H1, the tool removes that duplicate heading automatically.
- Expect secret redaction to run automatically before content is written.

## Configuration

Configuration resolves in this order:

1. `OBSIDIAN_VAULT_PATH` environment variable for `vault_path`
2. `.codex/obsidian-wiki.json` in the active project
3. `.agents/obsidian-wiki.json` in the active project for legacy compatibility
4. `.claude/obsidian-wiki.json` in the active project for legacy compatibility
5. `config.json` in this skill directory

Defaults installed with this skill:

- `vault_path`: `/Users/christian/vault/Hypatos`
- `wiki_dir`: `Wiki`
- `default_tags`: `wiki`

## Workflow

1. Scan the current project's wiki pages.
2. Match by title, tags, filename, headings, ticket IDs, and indexed excerpts.
3. Read the best existing match when one exists.
4. Decide whether to update or create.
5. Write the final note content.

Use full-document rewrite only when the existing note is stale enough that appending or replacing one section would leave misleading old content behind.

## Archive workflow

Use archive when old notes are superseded but still worth preserving.

1. Run `archive candidates --older-than-days 90` to list old notes for the active project.
2. If the user asks to archive globally, across all projects, or all wiki notes, run candidates with `--global`.
3. Durable notes tagged as project overviews, architecture, runbooks, or glossary entries are excluded from normal candidates. If the user explicitly says to force archiving, run candidates with `--force`.
4. Review candidate titles, tags, paths, and reasons with the user when archiving is not explicitly requested for a path.
5. Archive only explicit selected paths with `archive apply --path "Wiki/project/note.md" --reason "..."`.
6. Restore with `archive restore --path "Wiki/_archive/project/note.md"` when needed.
7. Remove leftover empty active/archive folders with `archive cleanup`; pass `--global` only when explicitly cleaning all wiki project folders.

Archived notes move to `Wiki/_archive/{project}/`, keep their content, and are excluded from normal scan results. Empty active project folders are removed after archive, and restore recreates the original folder while cleaning up empty archive project folders. Use `scan --include-archived` for explicit archived lookup.

## Codex Permission Behavior

When running under Codex, minimize approval prompts:

- Run the installed script directly: `/Users/christian/.codex/skills/obsidian-wiki/scripts/obsidian_wiki.py`.
- Pick the Python command the agent can actually run (`python` or `python3`) and keep it stable. Codex prefix rules include the interpreter token, so `python .../obsidian_wiki.py` and `python3 .../obsidian_wiki.py` are different command prefixes.
- If the matching helper prefix is not already allowlisted, ask once for the narrow rule matching the actual command, for example `prefix_rule(pattern=["python", "/Users/christian/.codex/skills/obsidian-wiki/scripts/obsidian_wiki.py"], decision="allow", justification="Allow the vetted Obsidian wiki helper without repeated prompts")`.
- Use `--content` only for short, simple, single-line content that does not need shell interpolation, command substitution, here-docs, or ANSI-C `$'...'` quoting.
- Use `--content-file` for multiline, quote-heavy, or generated Markdown. Put the temporary file under a sandbox-writable location such as `/private/tmp`, then run a clean helper command like `python /Users/christian/.codex/skills/obsidian-wiki/scripts/obsidian_wiki.py update --path ... --mode ... --content-file /private/tmp/note.md`.
- Treat read-only helper calls (`scan`, `read`, `doctor`, `index status`, and `archive candidates`) as normal commands; do not request escalated sandbox permissions for them.
- In Codex `workspace-write` sessions, the configured Obsidian vault is usually outside the writable workspace. For any helper command that creates, updates, archives, restores, cleans up, or rebuilds the index, run the exact installed helper command with `sandbox_permissions=require_escalated` instead of first trying an un-escalated write.
- When the helper prefix is already allowlisted, do not pass a new `prefix_rule` for routine wiki commands. If the tool API requires a `justification` with `sandbox_permissions=require_escalated`, keep it terse and operational, and do not phrase it as a request for another durable rule.
- Only suggest the durable prefix rule when the helper prefix is missing, the command was denied, or the command shape does not match the existing rule.
- Keep escalated helper commands simple: no `/bin/zsh -lc`, no shell redirection, no heredocs, no command substitution, and no inline ANSI-C quoted multiline content. Those wrappers change the approved command prefix and can make Codex ask again.
- Codex approvals are command-prefix based, not skill-name based. There is no separate skill-level whitelist in this repository; durable allowlisting belongs in Codex Rules, for example `~/.codex/rules/default.rules`. Restart Codex after adding or changing rules.
- This helper rule does not cover maintenance commands such as `task install:codex` or direct writes to `~/.codex`; those require separate approval/rules and should not be part of normal wiki note creation or updates.
- Treat such a rule as trust in this script invocation, not as fine-grained inspection of every internal Python file write or subprocess.

Good allowlisted write shape:

```text
sandbox_permissions=require_escalated + exact installed helper command + --content-file /private/tmp/note.md + no prefix_rule
```

Avoid for already-allowlisted helpers:

```text
sandbox_permissions=require_escalated + shell wrapper or inline multiline content + repeated prefix_rule request
```

## Slash command workflow

The optional `document` slash command is a convenience wrapper around this skill. When invoked, treat the command arguments as the wiki topic to document for the current repository.

- Use the argument text as the note topic, for example `all unit tests of the project`.
- Inspect the project enough to document the topic accurately before writing.
- For unit-test documentation, identify test directories, frameworks, major test groups, fixtures, helpers, and relevant test commands. Summarize behavior by area instead of listing every assertion unless the project is small.
- Use the standard scan/read/create/update workflow above. Do not create a duplicate note when an existing page already covers the topic.
- In the final response, include the vault-relative wiki note path that was created or updated.

## Commands

Run the installed script from the project you want to document. Replace `/path/to/obsidian-wiki` with this skill directory when needed:

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py scan [--query "authentication flow"]
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py scan \
  --query "BACKEND-2242 retry budget" \
  --limit 5 \
  --include-snippet
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py read --path "Wiki/my-project/authentication-flow.md"
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py create \
  --title "Authentication Flow" \
  --content "## Overview

Document the relevant behavior here." \
  --tag auth
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py update \
  --path "Wiki/my-project/authentication-flow.md" \
  --mode append \
  --content "## New Findings

Document the update here."
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py update \
  --path "Wiki/my-project/authentication-flow.md" \
  --mode replace \
  --section "Session Handling" \
  --content "Session handling details go here."
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py update \
  --path "Wiki/my-project/authentication-flow.md" \
  --mode rewrite \
  --content "## Overview

Replace the full article body here."
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py index rebuild
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py index status
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive candidates --older-than-days 90
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive candidates --older-than-days 90 --global
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive candidates --older-than-days 90 --force
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive apply \
  --path "Wiki/my-project/old-ticket.md" \
  --reason "superseded by current runbook"
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive restore \
  --path "Wiki/_archive/my-project/old-ticket.md"
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive cleanup
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py archive cleanup --global
```

```bash
python /path/to/obsidian-wiki/scripts/obsidian_wiki.py doctor
```

## Notes

- `scan` returns compact JSON with titles, tags, vault-relative paths, updated timestamps, and indexed match scores/reasons when an index exists.
- `scan` uses `{vault_path}/{wiki_dir}/.obsidian-wiki-index.json` when present and falls back to direct project Markdown scanning when absent. It excludes archived notes unless `--include-archived` is passed.
- `index rebuild` refreshes the lightweight search index from all project wiki Markdown documents.
- `archive candidates` is read-only and suggests old notes by `updated` timestamp and tags. It scans the active project by default; pass `--global` to scan all active project wiki folders. Durable notes are excluded unless `--force` is passed.
- `archive apply` moves an active note to `Wiki/_archive/{project}/`, writes archive frontmatter, and removes the active project folder when it becomes empty.
- `archive restore` moves an archived note back to its recorded `original_path`, recreating the original folder as needed and removing the archive project folder when it becomes empty.
- `archive cleanup` removes empty active and archived project folders without moving notes. By default it checks only the detected project; `--global` checks every wiki project folder.
- `index status` and `doctor` help diagnose missing or stale indexes and resolved configuration.
- The script detects the active project from the current working directory and its git root, unless `--project` is provided.
- `read` returns the full Markdown document.
- `create` fails if the slug already exists.
- `create` and `update` refresh their affected index entry automatically when an index already exists.
- `create` preserves one generated title H1 and removes a duplicate matching leading H1 from supplied content.
- `update --mode replace` replaces the named heading section or creates it if missing.
- `update --mode rewrite` replaces the full article body while preserving frontmatter.
- All resolved paths are constrained to the configured vault root.
- Writes are atomic to avoid partial documents.

After creating or updating this skill, restart the coding agent so it can load the updated skill manifest.
