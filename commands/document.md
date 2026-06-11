Document the requested topic for the current project in the Obsidian wiki.

The user invoked `/document` with this topic:

```text
$ARGUMENTS
```

If `$ARGUMENTS` was not expanded by this agent, infer the topic from the text after `/document` in the user's message.

Use the `obsidian-wiki` skill. Inspect the current repository enough to document the topic accurately, then scan existing wiki pages before deciding whether to update or create a note.

For requests like "all unit tests of the project", document the test layout, frameworks, major test groups, fixtures/helpers, and relevant commands. Summarize tests by behavior or subsystem instead of listing every assertion unless the project is small.

Never write wiki files directly. Use the installed `scripts/obsidian_wiki.py` scan/read/create/update workflow from the `obsidian-wiki` skill. End by telling the user which vault-relative wiki note path was created or updated.
