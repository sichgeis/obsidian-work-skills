---
name: obsidian-work-tasks
description: Create, update, scan, complete, and archive lightweight personal work-task notes in Obsidian. Use when the user asks to create work tasks, note progress on a task, mark a task done or blocked, plan work by task notes, or manage fine-grained work todos outside Jira.
---

# Obsidian Work Tasks

Use this skill when a user wants persistent personal work-task notes written into Obsidian. Do not use it when the user explicitly opts out of task or Obsidian logging.

## Required Behavior

- Never write work-task notes directly. Use `scripts/obsidian_work_tasks.py` for scan, read, create, update, archive, and index operations.
- Resolve `scripts/obsidian_work_tasks.py` relative to this skill directory when the current working directory is not the installed skill directory.
- Run the script from the project being worked on, or pass `--project` when the source project needs an explicit override.
- Store all active tasks under `{vault_path}/{tasks_dir}/`.
- Keep one Markdown file per task.
- Before creating a task, always scan for possible matches, especially Jira IDs, slugs, and similar titles.
- If a likely match exists, read it before deciding whether to update or create.
- Prefer updating an existing task when the slug, Jira ID, or title clearly matches.
- Treat "mark done" as `update --status done`, preserving notes and checklist content.
- Treat "mark blocked" as `update --status blocked`, with a short note explaining the blocker when possible.
- Treat "delete" or "remove" as archive by default. Do not hard-delete tasks in v1.
- Update the task index after every create, update, or archive. The script does this automatically.
- Expect secret redaction to run automatically before content is written.

## Task Content

Tasks use lightweight frontmatter and free-form Markdown. The default body has:

```markdown
## Checklist
- [ ] Define the next concrete step.

## Notes

## Links

## Log
```

Use `## Checklist` for plain Markdown checkbox subtasks. Use `## Notes` for current context, `## Links` for Jira, PRs, `[[Wiki/...]]`, and `[[Glossary/...]]` links, and `## Log` for dated progress notes.

## Configuration

Configuration resolves in this order:

1. `OBSIDIAN_VAULT_PATH` environment variable for `vault_path`
2. `.codex/obsidian-work-tasks.json` in the active project
3. `.agents/obsidian-work-tasks.json` in the active project for legacy compatibility
4. `.claude/obsidian-work-tasks.json` in the active project for legacy compatibility
5. `config.json` in this skill directory

Defaults installed with this skill:

- `vault_path`: `/Users/christian/vault/Hypatos`
- `tasks_dir`: `Work Tasks`
- `index_file`: `Index.md`
- `default_tags`: `work-task`

## Codex Permission Behavior

When running under Codex, minimize approval prompts:

- Use the installed script path: `/Users/christian/.codex/skills/obsidian-work-tasks/scripts/obsidian_work_tasks.py`.
- Use `--content` only for short, simple, single-line content that does not need shell interpolation, command substitution, here-docs, or ANSI-C `$'...'` quoting.
- Use `--content-file` for multiline, quote-heavy, or generated Markdown. Put the temporary file under a sandbox-writable location such as `/private/tmp`, then run a clean helper command like `python /Users/christian/.codex/skills/obsidian-work-tasks/scripts/obsidian_work_tasks.py update --path ... --mode append --content-file /private/tmp/worktask.md`.
- If Codex asks for command approval, allow the prefix `python /Users/christian/.codex/skills/obsidian-work-tasks/scripts/obsidian_work_tasks.py` for future runs.
- In Codex `workspace-write` sessions, the configured Obsidian vault is usually outside the writable workspace. For commands that create, update, archive, or regenerate the index, use `sandbox_permissions=require_escalated`.
- Treat read-only helper calls (`scan`, `read`, and `doctor`) as normal commands.

## Slash Command Workflow

The optional `/worktask` slash command is a convenience wrapper around this skill. When invoked, treat the command arguments as a work-task management request.

- For a create request, scan first and create only when no likely existing task matches.
- For an update request, scan/read the likely task and append or replace the relevant section.
- For "mark done" or "mark blocked", update only the status unless the user supplied note content.
- In the final response, include the vault-relative task path that was created, updated, or archived.

## Commands

Run the installed script from the project you want to associate with the task. Replace `/path/to/obsidian-work-tasks` with this skill directory when needed:

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py scan --query "BACKEND-1111"
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py create \
  --title "BACKEND-1111 Smoke test important bug" \
  --slug "BACKEND-1111" \
  --status doing \
  --priority high \
  --content-file /private/tmp/worktask.md
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py update \
  --path "Work Tasks/backend-1111.md" \
  --mode append \
  --content-file /private/tmp/worktask.md
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py update \
  --path "Work Tasks/backend-1111.md" \
  --status done
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py archive \
  --path "Work Tasks/backend-1111.md" \
  --reason "completed and no longer active"
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py index
```

```bash
python /path/to/obsidian-work-tasks/scripts/obsidian_work_tasks.py doctor
```

## Notes

- `scan` returns JSON with task titles, paths, statuses, priority, project, Jira ID, planning dates, tags, and updated timestamp.
- `read` returns the full Markdown document.
- `create` fails if the normalized task filename already exists.
- `update --mode replace` replaces the named heading section or creates it if missing.
- `update --mode rewrite` replaces the full task body while preserving frontmatter.
- `archive` moves active tasks into `Work Tasks/_archive/` and excludes them from active index groups.
- All resolved paths are constrained to the configured vault root.
- Writes are atomic to avoid partial documents.

After creating or updating this skill, restart the coding agent so it can load the updated skill manifest.
