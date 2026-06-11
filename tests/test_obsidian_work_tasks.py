from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "obsidian_work_tasks.py"


class WorkTasksCliTest(unittest.TestCase):
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

    def create_task(self, title: str = "BACKEND-1111 Smoke Test Important Bug", *extra_args: str) -> dict[str, object]:
        return self.json_cli(
            "--project",
            "invoice-service",
            "create",
            "--title",
            title,
            "--slug",
            "BACKEND-1111",
            "--status",
            "doing",
            "--tag",
            "smoke-test",
            "--content",
            "## Checklist\n- [ ] Reproduce with SECRET=topsecret\n\n## Notes\nInitial context.",
            *extra_args,
        )

    def test_create_writes_frontmatter_redacted_content_and_index(self) -> None:
        payload = self.create_task()

        self.assertEqual(payload["path"], "Work Tasks/backend-1111.md")
        task = (self.vault / "Work Tasks" / "backend-1111.md").read_text()
        self.assertIn("status: doing", task)
        self.assertIn("project: invoice-service", task)
        self.assertIn("jira_id: BACKEND-1111", task)
        self.assertIn("tags:\n  - work-task\n  - project/invoice-service\n  - smoke-test", task)
        self.assertIn("# BACKEND-1111 Smoke Test Important Bug", task)
        self.assertIn("SECRET: [REDACTED]", task)
        self.assertNotIn("title:", task)
        self.assertNotIn("slug:", task)
        self.assertNotIn("priority:", task)
        self.assertNotIn("planned_for:", task)
        self.assertNotIn("due:", task)

        index = (self.vault / "Work Tasks" / "Index.md").read_text()
        self.assertIn("# Work Tasks Index", index)
        self.assertIn("## Doing", index)
        self.assertIn("[[backend-1111\\|BACKEND-1111 Smoke Test Important Bug]]", index)
        self.assertIn("BACKEND-1111", index)
        self.assertIn("| Task | Status | Project | Jira | Updated |", index)

    def test_removed_metadata_flags_are_rejected(self) -> None:
        create_result = self.run_cli(
            "create",
            "--title",
            "Legacy priority",
            "--priority",
            "high",
            check=False,
        )

        self.assertNotEqual(create_result.returncode, 0)
        self.assertIn("unrecognized arguments: --priority high", create_result.stderr)

        self.create_task()
        update_result = self.run_cli(
            "update",
            "--path",
            "Work Tasks/backend-1111.md",
            "--due",
            "2026-06-12",
            check=False,
        )

        self.assertNotEqual(update_result.returncode, 0)
        self.assertIn("unrecognized arguments: --due 2026-06-12", update_result.stderr)

    def test_duplicate_create_fails(self) -> None:
        self.create_task()

        result = self.run_cli("create", "--title", "Different", "--slug", "BACKEND-1111", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_read_rejects_path_outside_vault(self) -> None:
        result = self.run_cli("read", "--path", "../outside.md", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes the vault root", result.stderr)

    def test_scan_matches_title_status_jira_project_tag_and_body(self) -> None:
        self.create_task()
        self.json_cli("--project", "review-service", "create", "--title", "Review queue cleanup", "--status", "todo", "--content", "Triage vendor notes.")
        tasks_dir = self.vault / "Work Tasks"
        (tasks_dir / "TaskNotes Setup.md").write_text("# TaskNotes Setup\n\nReference note.")

        jira_payload = self.json_cli("scan", "--query", "BACKEND-1111")
        status_payload = self.json_cli("scan", "--status", "doing")
        project_payload = self.json_cli("scan", "--query", "invoice-service")
        tag_payload = self.json_cli("scan", "--query", "smoke-test")
        body_payload = self.json_cli("scan", "--query", "vendor notes")
        setup_payload = self.json_cli("scan", "--query", "TaskNotes Setup")

        self.assertEqual([task["title"] for task in jira_payload["tasks"]], ["BACKEND-1111 Smoke Test Important Bug"])
        self.assertEqual([task["title"] for task in status_payload["tasks"]], ["BACKEND-1111 Smoke Test Important Bug"])
        self.assertEqual([task["title"] for task in project_payload["tasks"]], ["BACKEND-1111 Smoke Test Important Bug"])
        self.assertEqual([task["title"] for task in tag_payload["tasks"]], ["BACKEND-1111 Smoke Test Important Bug"])
        self.assertEqual([task["title"] for task in body_payload["tasks"]], ["Review queue cleanup"])
        self.assertEqual(setup_payload["tasks"], [])
        self.assertNotIn("slug", jira_payload["tasks"][0])
        self.assertNotIn("priority", jira_payload["tasks"][0])
        self.assertNotIn("planned_for", jira_payload["tasks"][0])
        self.assertNotIn("due", jira_payload["tasks"][0])

    def test_update_append_replace_rewrite_and_status_change_preserve_metadata(self) -> None:
        self.create_task()

        self.json_cli(
            "--project",
            "review-service",
            "update",
            "--path",
            "Work Tasks/backend-1111.md",
            "--mode",
            "append",
            "--tag",
            "review",
            "--content",
            "## Log\n2026-06-11: Found token abcdefabcdefabcdefabcdefabcdefabcdef.",
        )
        self.json_cli(
            "update",
            "--path",
            "Work Tasks/backend-1111.md",
            "--mode",
            "replace",
            "--section",
            "Notes",
            "--content",
            "Updated notes after reproduction.",
        )
        self.json_cli("update", "--path", "Work Tasks/backend-1111.md", "--status", "done")
        self.json_cli(
            "update",
            "--path",
            "Work Tasks/backend-1111.md",
            "--mode",
            "rewrite",
            "--content",
            "## Checklist\n- [x] Done\n\n## Notes\nRewritten final notes.",
        )

        task = (self.vault / "Work Tasks" / "backend-1111.md").read_text()
        self.assertIn("status: done", task)
        self.assertIn("project: invoice-service", task)
        self.assertIn("  - project/review-service", task)
        self.assertIn("  - review", task)
        self.assertIn("# BACKEND-1111 Smoke Test Important Bug", task)
        self.assertNotIn("title:", task)
        self.assertNotIn("slug:", task)
        self.assertNotIn("priority:", task)
        self.assertNotIn("planned_for:", task)
        self.assertNotIn("due:", task)
        self.assertIn("## Notes\nRewritten final notes.", task)
        self.assertNotIn("Updated notes after reproduction.", task)
        self.assertNotIn("abcdefabcdefabcdef", task)

        index = (self.vault / "Work Tasks" / "Index.md").read_text()
        self.assertIn("## Done", index)
        self.assertIn("[[backend-1111\\|BACKEND-1111 Smoke Test Important Bug]]", index)

    def test_archive_moves_task_out_of_active_index(self) -> None:
        self.create_task()

        payload = self.json_cli("archive", "--path", "Work Tasks/backend-1111.md", "--reason", "completed")

        self.assertEqual(payload["path"], "Work Tasks/_archive/backend-1111.md")
        self.assertFalse((self.vault / "Work Tasks" / "backend-1111.md").exists())
        archived = (self.vault / "Work Tasks" / "_archive" / "backend-1111.md").read_text()
        self.assertIn("archived: true", archived)
        self.assertIn("archived_reason: completed", archived)
        self.assertIn("original_path: Work Tasks/backend-1111.md", archived)

        index = (self.vault / "Work Tasks" / "Index.md").read_text()
        self.assertNotIn("[[backend-1111\\|BACKEND-1111 Smoke Test Important Bug]]", index)
        self.assertIn("Archived tasks: 1", index)

        active_scan = self.json_cli("scan", "--query", "BACKEND-1111")
        archived_scan = self.json_cli("scan", "--query", "BACKEND-1111", "--include-archived")
        self.assertEqual(active_scan["tasks"], [])
        self.assertEqual(len(archived_scan["tasks"]), 1)

    def test_compact_removes_legacy_metadata_fields(self) -> None:
        self.create_task()
        path = self.vault / "Work Tasks" / "backend-1111.md"
        task = path.read_text()
        path.write_text(
            task.replace(
                "---\n",
                "---\n"
                "title: BACKEND-1111 Smoke Test Important Bug\n"
                "slug: BACKEND-1111\n"
                "priority: high\n"
                "planned_for: 2026-06-11\n"
                "due: 2026-06-12\n",
                1,
            )
        )

        payload = self.json_cli("compact")

        self.assertEqual(payload["count"], 1)
        compacted = path.read_text()
        self.assertNotIn("title:", compacted)
        self.assertNotIn("slug:", compacted)
        self.assertNotIn("priority:", compacted)
        self.assertNotIn("planned_for:", compacted)
        self.assertNotIn("due:", compacted)
        self.assertIn("# BACKEND-1111 Smoke Test Important Bug", compacted)

    def test_index_command_regenerates_index(self) -> None:
        self.create_task()
        (self.vault / "Work Tasks" / "Index.md").unlink()

        payload = self.json_cli("index")

        self.assertEqual(payload["path"], "Work Tasks/Index.md")
        self.assertTrue((self.vault / "Work Tasks" / "Index.md").exists())

    def test_doctor_reports_configuration_and_paths(self) -> None:
        payload = self.json_cli("--project", "invoice-service", "doctor")

        self.assertEqual(payload["project"], "invoice-service")
        self.assertEqual(payload["vault_path"], str(self.vault.resolve()))
        self.assertEqual(payload["tasks_dir"], "Work Tasks")
        self.assertEqual(payload["index_file"], "Index.md")
        self.assertFalse(payload["tasks_exists"])
        self.assertFalse(payload["index_exists"])
        self.assertTrue(payload["writes_possible"])


if __name__ == "__main__":
    unittest.main()
