from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MCP_PATH = SCRIPTS_DIR / "obsidian_wiki_mcp.py"
SPEC = importlib.util.spec_from_file_location("obsidian_wiki_mcp", MCP_PATH)
assert SPEC and SPEC.loader
obsidian_wiki_mcp = importlib.util.module_from_spec(SPEC)
sys.modules["obsidian_wiki_mcp"] = obsidian_wiki_mcp
SPEC.loader.exec_module(obsidian_wiki_mcp)
obsidian_wiki = obsidian_wiki_mcp.wiki


class McpWikiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.project_root = self.root / "demo-project"
        self.project_root.mkdir()
        self.vault_path = self.root / "vault"
        config_dir = self.project_root / ".agents"
        config_dir.mkdir()
        (config_dir / "obsidian-wiki.json").write_text(
            json.dumps(
                {
                    "vault_path": str(self.vault_path),
                    "wiki_dir": "Wiki",
                    "default_tags": ["wiki"],
                }
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class McpContextTest(McpWikiTestCase):
    def test_resolve_context_uses_project_root_and_project_override(self) -> None:
        context = obsidian_wiki_mcp.resolve_context(
            project="manual-project",
            project_root=str(self.project_root),
        )

        self.assertEqual(context.project_root, self.project_root)
        self.assertEqual(context.project_name, "manual-project")
        self.assertEqual(context.config.vault_path, self.vault_path)

    def test_resolve_context_detects_project_from_project_root(self) -> None:
        context = obsidian_wiki_mcp.resolve_context(project_root=str(self.project_root))

        self.assertEqual(context.project_name, "demo-project")


class McpWrapperTest(McpWikiTestCase):
    def test_create_scan_and_read_note_use_existing_domain_behavior(self) -> None:
        created = obsidian_wiki_mcp.create_note(
            "Authentication Flow",
            "## Overview\n\nToken handling details.",
            ["auth"],
            project="demo",
            project_root=str(self.project_root),
        )

        scanned = obsidian_wiki_mcp.scan_wiki(
            query="Authentication",
            project="demo",
            project_root=str(self.project_root),
        )
        body = obsidian_wiki_mcp.read_note(created["path"], project_root=str(self.project_root))

        self.assertEqual(created["path"], "Wiki/demo/authentication-flow.md")
        self.assertEqual(scanned["project"], "demo")
        self.assertEqual(scanned["documents"][0]["title"], "Authentication Flow")
        self.assertIn("Token handling details.", body)

    def test_update_note_redacts_and_refreshes_existing_index(self) -> None:
        created = obsidian_wiki_mcp.create_note(
            "Existing Ticket",
            "## Context\n\nOld.",
            ["ticket"],
            project="demo",
            project_root=str(self.project_root),
        )
        obsidian_wiki_mcp.index_rebuild(project_root=str(self.project_root))

        obsidian_wiki_mcp.update_note(
            created["path"],
            "append",
            "## Follow Up\n\nAPI_KEY=super-secret-token\n\nNew searchable phrase.",
            project="demo",
            project_root=str(self.project_root),
        )

        scanned = obsidian_wiki_mcp.scan_wiki(
            query="searchable phrase",
            project="demo",
            project_root=str(self.project_root),
        )
        body = obsidian_wiki_mcp.read_note(created["path"], project_root=str(self.project_root))

        self.assertEqual(scanned["documents"][0]["title"], "Existing Ticket")
        self.assertIn("API_KEY: [REDACTED]", body)
        self.assertNotIn("super-secret-token", body)

    def test_archive_wrappers_move_restore_and_report_status(self) -> None:
        created = obsidian_wiki_mcp.create_note(
            "Old Ticket",
            "Body",
            ["ticket"],
            project="demo",
            project_root=str(self.project_root),
        )

        archived = obsidian_wiki_mcp.archive_apply(
            created["path"],
            "superseded",
            project_root=str(self.project_root),
        )
        archived_status = obsidian_wiki_mcp.archive_status(project="demo", project_root=str(self.project_root))
        restored = obsidian_wiki_mcp.archive_restore(
            archived["path"],
            project_root=str(self.project_root),
        )

        self.assertEqual(archived["path"], "Wiki/_archive/demo/old-ticket.md")
        self.assertEqual(archived_status["archived_documents"], 1)
        self.assertEqual(restored["path"], created["path"])

    def test_update_note_surfaces_existing_wiki_errors(self) -> None:
        created = obsidian_wiki_mcp.create_note(
            "Needs Section",
            "Body",
            project="demo",
            project_root=str(self.project_root),
        )

        with self.assertRaisesRegex(obsidian_wiki.WikiError, "--section is required"):
            obsidian_wiki_mcp.update_note(
                created["path"],
                "replace",
                "New",
                project="demo",
                project_root=str(self.project_root),
            )


if __name__ == "__main__":
    unittest.main()
