Manage the requested work task in Obsidian.

The user invoked `/worktask` with this request:

```text
$ARGUMENTS
```

If `$ARGUMENTS` was not expanded by this agent, infer the request from the text after `/worktask` in the user's message.

Use the `obsidian-work-tasks` skill. Scan existing tasks before creating a new one, especially for Jira IDs, slugs, and similar titles. Read likely matches before updating them.

Never write work-task files directly. Use the installed `scripts/obsidian_work_tasks.py` scan/read/create/update/archive workflow from the `obsidian-work-tasks` skill. Treat delete/remove as archive by default. End by telling the user which vault-relative task note path was created, updated, or archived.
