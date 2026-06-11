from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "obsidian_glossary.py"


class GlossaryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "source-project"
        self.project.mkdir()
        self.vault = self.root / "vault"
        self.vault.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        merged_env["OBSIDIAN_VAULT_PATH"] = str(self.vault)
        if env:
            merged_env.update(env)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd or self.project,
            env=merged_env,
            text=True,
            capture_output=True,
        )
        if check and result.returncode != 0:
            self.fail(f"Command failed: {result.stderr}\nstdout: {result.stdout}")
        return result

    def json_cli(self, *args: str, **kwargs: object) -> dict[str, object]:
        result = self.run_cli(*args, **kwargs)
        return json.loads(result.stdout)

    def create_entry(self, term: str = "Accounting Data", *extra_args: str) -> dict[str, object]:
        alias = term.lower().replace(" ", "_")
        return self.json_cli(
            "--project",
            "invoice-service",
            "create",
            "--term",
            term,
            "--summary",
            "Accounting payload used by invoice extraction.",
            "--alias",
            alias,
            "--tag",
            "finance",
            "--content",
            "## Meaning\nAccounting Data means SECRET=topsecret in this context.",
            *extra_args,
        )

    def test_create_writes_frontmatter_redacted_content_and_index(self) -> None:
        payload = self.create_entry()

        self.assertEqual(payload["path"], "Glossary/accounting-data.md")
        entry = (self.vault / "Glossary" / "accounting-data.md").read_text()
        self.assertIn("title: Accounting Data", entry)
        self.assertIn("canonical_term: Accounting Data", entry)
        self.assertIn("source_projects:\n  - invoice-service", entry)
        self.assertIn("tags:\n  - glossary\n  - project/invoice-service\n  - finance", entry)
        self.assertIn("# Accounting Data", entry)
        self.assertIn("SECRET: [REDACTED]", entry)

        index = (self.vault / "Glossary" / "Index.md").read_text()
        self.assertIn("[[accounting-data\\|Accounting Data]]", index)
        self.assertIn("Accounting payload used by invoice extraction.", index)

    def test_duplicate_create_fails(self) -> None:
        self.create_entry()

        result = self.run_cli("create", "--term", "Accounting Data", "--content", "## Meaning\nAgain", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_read_rejects_path_outside_vault(self) -> None:
        result = self.run_cli("read", "--path", "../outside.md", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes the vault root", result.stderr)

    def test_scan_matches_alias_tag_filename_and_respects_limit(self) -> None:
        self.create_entry("Accounting Data")
        self.create_entry("Vendor Name")

        alias_payload = self.json_cli("scan", "--query", "accounting_data")
        tag_payload = self.json_cli("scan", "--query", "finance")
        filename_payload = self.json_cli("scan", "--query", "vendor-name")
        limited_payload = self.json_cli("scan", "--limit", "1")

        self.assertEqual([entry["canonical_term"] for entry in alias_payload["entries"]], ["Accounting Data"])
        self.assertEqual([entry["canonical_term"] for entry in tag_payload["entries"]], ["Accounting Data", "Vendor Name"])
        self.assertEqual([entry["canonical_term"] for entry in filename_payload["entries"]], ["Vendor Name"])
        self.assertEqual(len(limited_payload["entries"]), 1)

    def test_update_append_replace_and_rewrite_preserve_metadata(self) -> None:
        self.create_entry()

        self.json_cli(
            "--project",
            "review-service",
            "update",
            "--path",
            "Glossary/accounting-data.md",
            "--mode",
            "append",
            "--alias",
            "accounting payload",
            "--content",
            "## Product Context\nUsed during review.",
        )
        self.json_cli(
            "update",
            "--path",
            "Glossary/accounting-data.md",
            "--mode",
            "replace",
            "--section",
            "Product Context",
            "--content",
            "Used after extraction.",
        )
        self.json_cli(
            "update",
            "--path",
            "Glossary/accounting-data.md",
            "--mode",
            "rewrite",
            "--content",
            "## Meaning\nRewritten meaning with token: abcdefabcdefabcdefabcdefabcdefabcdef.",
        )

        entry = (self.vault / "Glossary" / "accounting-data.md").read_text()
        self.assertIn("title: Accounting Data", entry)
        self.assertIn("canonical_term: Accounting Data", entry)
        self.assertIn("  - invoice-service", entry)
        self.assertIn("  - review-service", entry)
        self.assertIn("  - accounting payload", entry)
        self.assertIn("## Meaning\nRewritten meaning with token: [REDACTED]", entry)
        self.assertNotIn("Used after extraction.", entry)

        index = (self.vault / "Glossary" / "Index.md").read_text()
        self.assertIn("[[accounting-data\\|Accounting Data]]", index)

    def test_doctor_reports_configuration_and_paths(self) -> None:
        payload = self.json_cli("--project", "invoice-service", "doctor")

        self.assertEqual(payload["project"], "invoice-service")
        self.assertEqual(payload["vault_path"], str(self.vault.resolve()))
        self.assertEqual(payload["glossary_dir"], "Glossary")
        self.assertEqual(payload["index_file"], "Index.md")
        self.assertFalse(payload["glossary_exists"])
        self.assertFalse(payload["index_exists"])
        self.assertTrue(payload["writes_possible"])

    def test_project_config_is_used_when_environment_override_is_absent(self) -> None:
        configured_vault = self.root / "configured-vault"
        agents_dir = self.project / ".agents"
        agents_dir.mkdir()
        (agents_dir / "obsidian-glossary.json").write_text(
            json.dumps({"vault_path": str(configured_vault), "glossary_dir": "Terms"})
        )
        env = os.environ.copy()
        env.pop("OBSIDIAN_VAULT_PATH", None)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "doctor"],
            cwd=self.project,
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["vault_path"], str(configured_vault.resolve()))
        self.assertEqual(payload["glossary_dir"], "Terms")
        self.assertIn(str((agents_dir / "obsidian-glossary.json").resolve()), payload["config_sources"])


if __name__ == "__main__":
    unittest.main()
