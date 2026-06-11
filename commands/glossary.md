Research and document the requested term in the Hypatos Obsidian glossary.

The user invoked `/glossary` with this term:

```text
$ARGUMENTS
```

If `$ARGUMENTS` was not expanded by this agent, infer the term from the text after `/glossary` in the user's message.

Use the `hypatos-glossary` skill. Inspect the current repository enough to document the term accurately, then scan existing glossary entries before deciding whether to update or create a note.

Never write glossary files directly. Use the installed `scripts/obsidian_glossary.py` scan/read/create/update workflow from the `hypatos-glossary` skill. End by telling the user which vault-relative glossary note path was created or updated.
