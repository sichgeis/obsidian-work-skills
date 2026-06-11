from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obsidian_work import core


class CoreTest(unittest.TestCase):
    def test_config_helpers_merge_and_list_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            codex = project / ".codex"
            codex.mkdir(parents=True)
            config_path = codex / "obsidian-wiki.json"
            config_path.write_text(json.dumps({"vault_path": str(root / "vault"), "redaction": {"enabled": False}}))

            merged = core.deep_merge({"redaction": {"enabled": True, "patterns": ["TOKEN"]}}, {"redaction": {"enabled": False}})
            sources = core.config_source_paths(root / "skill.json", project, [Path(".codex") / "obsidian-wiki.json"])

            self.assertFalse(merged["redaction"]["enabled"])
            self.assertEqual(sources, [root / "skill.json", config_path])

    def test_path_confinement_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            self.assertEqual(core.ensure_within(root, root / "note.md"), root / "note.md")
            with self.assertRaisesRegex(core.ObsidianWorkError, "escapes the vault root"):
                core.ensure_within(root, root.parent / "outside.md")

    def test_frontmatter_round_trip(self) -> None:
        rendered = core.format_frontmatter({"title": "Example", "tags": ["wiki", "project/demo"], "archived": False})
        frontmatter, body = core.parse_frontmatter(rendered + "# Example\n")

        self.assertEqual(frontmatter["title"], "Example")
        self.assertEqual(frontmatter["tags"], ["wiki", "project/demo"])
        self.assertEqual(frontmatter["archived"], "false")
        self.assertEqual(body, "\n# Example\n")

    def test_redaction_atomic_write_and_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            content = core.redact_secrets("API_KEY=supersecretvalue and abcdefabcdefabcdefabcdefabcdef", True, ["API_KEY"])
            core.atomic_write(path, content)

            replaced = core.replace_section("# Title\n\n## Meaning\nOld\n\n## Next\nKeep", "Meaning", "New")

            self.assertIn("API_KEY: [REDACTED]", path.read_text())
            self.assertIn("[REDACTED]", path.read_text())
            self.assertIn("## Meaning\n\nNew", replaced)
            self.assertIn("## Next\nKeep", replaced)


if __name__ == "__main__":
    unittest.main()
