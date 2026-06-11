from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "obsidian_wiki.py"
SPEC = importlib.util.spec_from_file_location("obsidian_wiki", SCRIPT_PATH)
assert SPEC and SPEC.loader
obsidian_wiki = importlib.util.module_from_spec(SPEC)
sys.modules["obsidian_wiki"] = obsidian_wiki
SPEC.loader.exec_module(obsidian_wiki)


class WikiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_path = Path(self.temp_dir.name).resolve()
        self.config = obsidian_wiki.Config(
            vault_path=self.vault_path,
            wiki_dir="Wiki",
            default_tags=["wiki"],
            redaction_enabled=True,
            redaction_patterns=["API_KEY", "SECRET", "TOKEN", "PASSWORD"],
        )
        self.path = self.vault_path / "Wiki" / "demo" / "article.md"
        self.path.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def read_document_body(self, path: Path) -> str:
        _, body = obsidian_wiki.parse_frontmatter(path.read_text())
        return body.strip()


class CreateDocumentTest(WikiTestCase):
    def create_article(self, title: str, body: str) -> Path:
        result = obsidian_wiki.create_document(self.config, "demo", title, body, None)
        return self.vault_path / result["path"]

    def test_create_removes_duplicate_leading_title_heading(self) -> None:
        path = self.create_article("Authentication Flow", "# Authentication Flow\n\n## Overview\n\nDetails")

        self.assertEqual(
            self.read_document_body(path),
            "# Authentication Flow\n\n## Overview\n\nDetails",
        )

    def test_create_removes_duplicate_title_heading_case_insensitively(self) -> None:
        path = self.create_article("Authentication Flow", "# authentication flow\n\nDetails")

        self.assertEqual(self.read_document_body(path), "# Authentication Flow\n\nDetails")

    def test_create_preserves_non_matching_leading_h1(self) -> None:
        path = self.create_article("Authentication Flow", "# Session Flow\n\nDetails")

        self.assertEqual(self.read_document_body(path), "# Authentication Flow\n\n# Session Flow\n\nDetails")

    def test_create_preserves_lower_level_heading_content(self) -> None:
        path = self.create_article("Authentication Flow", "## Overview\n\nDetails")

        self.assertEqual(self.read_document_body(path), "# Authentication Flow\n\n## Overview\n\nDetails")

    def test_create_preserves_plain_body_content(self) -> None:
        path = self.create_article("Authentication Flow", "Details")

        self.assertEqual(self.read_document_body(path), "# Authentication Flow\n\nDetails")


class IndexSearchTest(WikiTestCase):
    def create_article(self, title: str, body: str, tags: list[str] | None = None) -> Path:
        result = obsidian_wiki.create_document(self.config, "demo", title, body, tags)
        return self.vault_path / result["path"]

    def test_rebuild_index_includes_document_metadata_headings_and_excerpt(self) -> None:
        self.create_article(
            "Allow Full Wiki Article Rewrite",
            "## Refined Ticket\n\nAllow replacing the complete article body.",
            ["ticket"],
        )

        payload = obsidian_wiki.rebuild_index(self.config)

        self.assertEqual(len(payload["documents"]), 1)
        entry = payload["documents"][0]
        self.assertEqual(entry["title"], "Allow Full Wiki Article Rewrite")
        self.assertEqual(entry["project"], "demo")
        self.assertIn("Refined Ticket", entry["headings"])
        self.assertIn("article", entry["tokens"])
        self.assertTrue((self.vault_path / "Wiki" / obsidian_wiki.INDEX_FILENAME).exists())

    def test_scan_uses_index_for_body_and_heading_matches(self) -> None:
        self.create_article(
            "Allow Full Wiki Article Rewrite",
            "## Refined Ticket\n\nAllow replacing the complete article body.",
            ["ticket"],
        )
        obsidian_wiki.rebuild_index(self.config)

        results = obsidian_wiki.scan_documents(self.config, "demo", "article body replace")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Allow Full Wiki Article Rewrite")
        self.assertEqual(results[0]["reason"], "title,body")

    def test_scan_matches_ticket_id_from_body(self) -> None:
        self.create_article(
            "LLM OCR Fallback Ticket",
            "## Context\n\nImplement BACKEND-2242 page-aware retry budgets.",
            ["ticket"],
        )
        obsidian_wiki.rebuild_index(self.config)

        results = obsidian_wiki.scan_documents(self.config, "demo", "backend-2242")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "LLM OCR Fallback Ticket")
        self.assertIn("ticket:BACKEND-2242", results[0]["reason"])

    def test_create_refreshes_existing_index_entry(self) -> None:
        obsidian_wiki.rebuild_index(self.config)

        self.create_article("New Ticket", "## Context\n\nFresh indexed content.", ["ticket"])

        results = obsidian_wiki.scan_documents(self.config, "demo", "fresh indexed")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "New Ticket")

    def test_update_refreshes_existing_index_entry(self) -> None:
        path = self.create_article("Existing Ticket", "## Context\n\nOld content.", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)

        obsidian_wiki.update_document(
            self.config,
            "demo",
            str(path.relative_to(self.vault_path)),
            "append",
            "## Follow Up\n\nNew searchable phrase.",
            None,
        )

        results = obsidian_wiki.scan_documents(self.config, "demo", "searchable phrase")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Existing Ticket")

    def test_index_status_reports_fresh_index(self) -> None:
        self.create_article("Existing Ticket", "Body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)

        status = obsidian_wiki.index_status(self.config)

        self.assertTrue(status["exists"])
        self.assertTrue(status["valid"])
        self.assertFalse(status["stale"])
        self.assertEqual(status["documents"], 1)

    def test_index_status_reports_changed_document_as_stale(self) -> None:
        path = self.create_article("Existing Ticket", "Body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)
        path.write_text(path.read_text() + "\nChanged outside the tool.\n")

        status = obsidian_wiki.index_status(self.config)

        self.assertTrue(status["stale"])
        self.assertEqual(status["stale_paths"], ["Wiki/demo/existing-ticket.md"])


class ArchiveDocumentTest(WikiTestCase):
    def create_article(self, title: str, body: str, tags: list[str] | None = None) -> Path:
        result = obsidian_wiki.create_document(self.config, "demo", title, body, tags)
        return self.vault_path / result["path"]

    def write_article_with_updated(self, title: str, updated: str, tags: list[str]) -> Path:
        path = self.vault_path / "Wiki" / "demo" / f"{obsidian_wiki.slugify(title)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        tag_lines = "\n".join(f"  - {tag}" for tag in tags)
        path.write_text(
            "\n".join(
                [
                    "---",
                    f"title: {title}",
                    "created: 2025-01-01T00:00:00+00:00",
                    f"updated: {updated}",
                    "project: demo",
                    "tags:",
                    tag_lines,
                    "---",
                    "",
                    f"# {title}",
                    "",
                    "Body",
                    "",
                ]
            )
        )
        return path

    def test_archive_candidates_excludes_durable_tags_by_default(self) -> None:
        self.write_article_with_updated("Old Ticket", "2025-01-01T00:00:00+00:00", ["wiki", "project/demo", "ticket"])
        self.write_article_with_updated("Architecture Overview", "2025-01-01T00:00:00+00:00", ["wiki", "project/demo", "architecture"])
        self.create_article("Fresh Ticket", "Body", ["ticket"])

        candidates = obsidian_wiki.archive_candidates(self.config, "demo", 90, 10)

        self.assertEqual([candidate["title"] for candidate in candidates], ["Old Ticket"])
        self.assertEqual(candidates[0]["reason"], "old_ticket_or_investigation")

    def test_archive_candidates_force_includes_durable_tags(self) -> None:
        self.write_article_with_updated("Old Ticket", "2025-01-01T00:00:00+00:00", ["wiki", "project/demo", "ticket"])
        self.write_article_with_updated("Architecture Overview", "2025-01-01T00:00:00+00:00", ["wiki", "project/demo", "architecture"])

        candidates = obsidian_wiki.archive_candidates(self.config, "demo", 90, 10, force=True)
        reasons_by_title = {candidate["title"]: candidate["reason"] for candidate in candidates}

        self.assertEqual(
            reasons_by_title,
            {
                "Old Ticket": "old_ticket_or_investigation",
                "Architecture Overview": "old_durable_note",
            },
        )

    def test_archive_candidates_global_lists_old_notes_across_projects(self) -> None:
        self.write_article_with_updated("Demo Old Ticket", "2025-01-01T00:00:00+00:00", ["wiki", "project/demo", "ticket"])
        other_project_path = self.vault_path / "Wiki" / "other" / "other-old-note.md"
        other_project_path.parent.mkdir(parents=True, exist_ok=True)
        other_project_path.write_text(
            "\n".join(
                [
                    "---",
                    "title: Other Old Note",
                    "created: 2025-01-01T00:00:00+00:00",
                    "updated: 2025-01-02T00:00:00+00:00",
                    "project: other",
                    "tags:",
                    "  - wiki",
                    "  - project/other",
                    "---",
                    "",
                    "# Other Old Note",
                    "",
                    "Body",
                    "",
                ]
            )
        )

        candidates = obsidian_wiki.archive_candidates_global(self.config, 90, 10)

        self.assertEqual(
            {candidate["title"]: candidate["project"] for candidate in candidates},
            {
                "Demo Old Ticket": "demo",
                "Other Old Note": "other",
            },
        )

    def test_archive_apply_moves_note_and_marks_frontmatter(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)

        result = obsidian_wiki.archive_document(
            self.config,
            str(path.relative_to(self.vault_path)),
            "superseded",
        )

        archive_path = self.vault_path / "Wiki" / "_archive" / "demo" / "old-ticket.md"
        self.assertFalse(path.exists())
        self.assertTrue(archive_path.exists())
        self.assertEqual(result["path"], "Wiki/_archive/demo/old-ticket.md")
        frontmatter, body = obsidian_wiki.parse_frontmatter(archive_path.read_text())
        self.assertEqual(frontmatter["archived"], "true")
        self.assertEqual(frontmatter["archived_reason"], "superseded")
        self.assertEqual(frontmatter["original_path"], "Wiki/demo/old-ticket.md")
        self.assertIn("Body", body)

    def test_archive_apply_removes_empty_active_project_directory(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])

        result = obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")

        self.assertTrue(result["active_directory_removed"])
        self.assertFalse((self.vault_path / "Wiki" / "demo").exists())

    def test_archive_apply_keeps_active_project_directory_when_not_empty(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])
        self.create_article("Remaining Note", "Body", ["ticket"])

        result = obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")

        self.assertFalse(result["active_directory_removed"])
        self.assertTrue((self.vault_path / "Wiki" / "demo").exists())
        self.assertTrue((self.vault_path / "Wiki" / "demo" / "remaining-note.md").exists())

    def test_scan_excludes_archived_notes_by_default(self) -> None:
        path = self.create_article("Old Ticket", "Searchable archived body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)
        obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")

        active_results = obsidian_wiki.scan_documents(self.config, "demo", "searchable", include_archived=False)
        archived_results = obsidian_wiki.scan_documents(self.config, "demo", "searchable", include_archived=True)

        self.assertEqual(active_results, [])
        self.assertEqual(len(archived_results), 1)
        self.assertTrue(archived_results[0]["archived"])
        self.assertEqual(archived_results[0]["path"], "Wiki/_archive/demo/old-ticket.md")

    def test_restore_moves_archived_note_to_original_path(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)
        archive_result = obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")

        restore_result = obsidian_wiki.restore_document(self.config, archive_result["path"])

        restored_path = self.vault_path / "Wiki" / "demo" / "old-ticket.md"
        archive_path = self.vault_path / "Wiki" / "_archive" / "demo" / "old-ticket.md"
        self.assertTrue(restored_path.exists())
        self.assertFalse(archive_path.exists())
        self.assertEqual(restore_result["path"], "Wiki/demo/old-ticket.md")
        self.assertTrue(restore_result["archive_directory_removed"])
        self.assertTrue((self.vault_path / "Wiki" / "demo").exists())
        self.assertFalse((self.vault_path / "Wiki" / "_archive" / "demo").exists())
        self.assertTrue((self.vault_path / "Wiki" / "_archive").exists())
        frontmatter, _ = obsidian_wiki.parse_frontmatter(restored_path.read_text())
        self.assertNotIn("archived", frontmatter)
        self.assertNotIn("original_path", frontmatter)

    def test_restore_keeps_archive_project_directory_when_not_empty(self) -> None:
        first_path = self.create_article("First Ticket", "Body", ["ticket"])
        second_path = self.create_article("Second Ticket", "Body", ["ticket"])
        first_archive = obsidian_wiki.archive_document(self.config, str(first_path.relative_to(self.vault_path)), "old")
        obsidian_wiki.archive_document(self.config, str(second_path.relative_to(self.vault_path)), "old")

        result = obsidian_wiki.restore_document(self.config, first_archive["path"])

        self.assertFalse(result["archive_directory_removed"])
        self.assertTrue((self.vault_path / "Wiki" / "demo").exists())
        self.assertTrue((self.vault_path / "Wiki" / "_archive" / "demo").exists())
        self.assertTrue((self.vault_path / "Wiki" / "_archive" / "demo" / "second-ticket.md").exists())

    def test_archive_cleanup_removes_empty_project_and_archive_directories(self) -> None:
        active_empty = self.vault_path / "Wiki" / "demo" / "empty" / "nested"
        archive_empty = self.vault_path / "Wiki" / "_archive" / "demo" / "empty"
        active_empty.mkdir(parents=True)
        archive_empty.mkdir(parents=True)

        result = obsidian_wiki.cleanup_empty_directories(self.config, "demo")

        self.assertEqual(result["scope"], "project")
        self.assertEqual(result["project"], "demo")
        self.assertEqual(result["removed_count"], 5)
        self.assertFalse((self.vault_path / "Wiki" / "demo").exists())
        self.assertFalse((self.vault_path / "Wiki" / "_archive" / "demo").exists())
        self.assertTrue((self.vault_path / "Wiki").exists())
        self.assertTrue((self.vault_path / "Wiki" / "_archive").exists())

    def test_archive_cleanup_keeps_non_empty_directories(self) -> None:
        path = self.create_article("Remaining Note", "Body", ["ticket"])
        empty_archive = self.vault_path / "Wiki" / "_archive" / "demo" / "empty"
        empty_archive.mkdir(parents=True)

        result = obsidian_wiki.cleanup_empty_directories(self.config, "demo")

        self.assertEqual(result["removed_directories"], ["Wiki/_archive/demo", "Wiki/_archive/demo/empty"])
        self.assertTrue(path.exists())
        self.assertTrue((self.vault_path / "Wiki" / "demo").exists())

    def test_archive_cleanup_global_removes_empty_directories_across_projects(self) -> None:
        (self.vault_path / "Wiki" / "demo" / "empty").mkdir(parents=True)
        (self.vault_path / "Wiki" / "other" / "empty").mkdir(parents=True)
        kept_path = self.vault_path / "Wiki" / "kept" / "note.md"
        kept_path.parent.mkdir(parents=True)
        kept_path.write_text("Body")

        result = obsidian_wiki.cleanup_empty_directories(self.config, "demo", global_scope=True)

        self.assertEqual(result["scope"], "global")
        self.assertIsNone(result["project"])
        self.assertFalse((self.vault_path / "Wiki" / "demo").exists())
        self.assertFalse((self.vault_path / "Wiki" / "other").exists())
        self.assertTrue(kept_path.exists())
        self.assertTrue((self.vault_path / "Wiki").exists())

    def test_restore_fails_when_destination_exists(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])
        archive_result = obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")
        self.create_article("Old Ticket", "Replacement", ["ticket"])

        with self.assertRaisesRegex(obsidian_wiki.WikiError, "Restore destination already exists"):
            obsidian_wiki.restore_document(self.config, archive_result["path"])

    def test_index_status_remains_fresh_after_archive_and_restore(self) -> None:
        path = self.create_article("Old Ticket", "Body", ["ticket"])
        obsidian_wiki.rebuild_index(self.config)
        archive_result = obsidian_wiki.archive_document(self.config, str(path.relative_to(self.vault_path)), "old")

        archived_status = obsidian_wiki.index_status(self.config)
        self.assertFalse(archived_status["stale"])
        self.assertEqual(archived_status["documents"], 1)

        obsidian_wiki.restore_document(self.config, archive_result["path"])
        restored_status = obsidian_wiki.index_status(self.config)
        self.assertFalse(restored_status["stale"])
        self.assertEqual(restored_status["documents"], 1)


class UpdateDocumentTest(WikiTestCase):
    def write_article(self, body: str, frontmatter: str | None = None) -> None:
        metadata = frontmatter or "\n".join(
            [
                "---",
                "title: Article",
                "created: 2026-01-01T00:00:00+00:00",
                "updated: 2026-01-01T00:00:00+00:00",
                "project: demo",
                "tags:",
                "  - wiki",
                "  - project/demo",
                "---",
            ]
        )
        self.path.write_text(f"{metadata}\n\n{body}\n")

    def read_body(self) -> str:
        return self.read_document_body(self.path)

    def read_frontmatter(self) -> dict[str, object]:
        frontmatter, _ = obsidian_wiki.parse_frontmatter(self.path.read_text())
        return frontmatter

    def test_append_mode_adds_content_to_existing_body(self) -> None:
        self.write_article("# Article\n\nExisting")

        obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "append",
            "## New Findings\n\nMore detail",
            None,
        )

        self.assertEqual(self.read_body(), "# Article\n\nExisting\n\n## New Findings\n\nMore detail")

    def test_replace_mode_replaces_named_section(self) -> None:
        self.write_article("# Article\n\n## Details\n\nOld\n\n## Other\n\nKeep")

        obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "replace",
            "New",
            "Details",
        )

        self.assertEqual(self.read_body(), "# Article\n\n## Details\n\nNew\n## Other\n\nKeep")

    def test_replace_mode_requires_section(self) -> None:
        self.write_article("# Article")

        with self.assertRaisesRegex(obsidian_wiki.WikiError, "--section is required"):
            obsidian_wiki.update_document(
                self.config,
                "demo",
                "Wiki/demo/article.md",
                "replace",
                "New",
                None,
            )

    def test_rewrite_mode_replaces_complete_body(self) -> None:
        self.write_article("# Article\n\n## Old\n\nStale")

        result = obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "rewrite",
            "## Overview\n\nNew complete article body.",
            None,
        )

        self.assertEqual(result["mode"], "rewrite")
        self.assertIsNone(result["section"])
        self.assertEqual(self.read_body(), "## Overview\n\nNew complete article body.")

    def test_rewrite_mode_preserves_frontmatter_and_refreshes_updated(self) -> None:
        self.write_article("# Article\n\nOld")

        obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "rewrite",
            "New",
            None,
        )

        frontmatter = self.read_frontmatter()
        self.assertEqual(frontmatter["title"], "Article")
        self.assertEqual(frontmatter["created"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(frontmatter["project"], "demo")
        self.assertEqual(frontmatter["tags"], ["wiki", "project/demo"])
        self.assertNotEqual(frontmatter["updated"], "2026-01-01T00:00:00+00:00")

    def test_rewrite_mode_fills_missing_project_and_tags(self) -> None:
        self.write_article(
            "# Article\n\nOld",
            "\n".join(
                [
                    "---",
                    "title: Article",
                    "created: 2026-01-01T00:00:00+00:00",
                    "updated: 2026-01-01T00:00:00+00:00",
                    "---",
                ]
            ),
        )

        obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "rewrite",
            "New",
            None,
        )

        frontmatter = self.read_frontmatter()
        self.assertEqual(frontmatter["project"], "demo")
        self.assertEqual(frontmatter["tags"], ["wiki", "project/demo"])

    def test_rewrite_mode_redacts_secrets(self) -> None:
        self.write_article("# Article\n\nOld")

        obsidian_wiki.update_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "rewrite",
            "API_KEY=super-secret-token",
            None,
        )

        self.assertEqual(self.read_body(), "API_KEY: [REDACTED]")

    def test_update_missing_document_raises_error(self) -> None:
        with self.assertRaisesRegex(obsidian_wiki.WikiError, "Document does not exist"):
            obsidian_wiki.update_document(
                self.config,
                "demo",
                "Wiki/demo/missing.md",
                "rewrite",
                "New",
                None,
            )

    def test_update_document_without_frontmatter_raises_error(self) -> None:
        self.path.write_text("# Article\n\nNo frontmatter\n")

        with self.assertRaisesRegex(obsidian_wiki.WikiError, "missing expected frontmatter"):
            obsidian_wiki.update_document(
                self.config,
                "demo",
                "Wiki/demo/article.md",
                "rewrite",
                "New",
                None,
            )


class AddFrontmatterTest(WikiTestCase):
    def test_add_frontmatter_preserves_body_and_uses_file_mtime(self) -> None:
        self.path.write_text("# Existing Title\n\nBody\n")
        os.utime(self.path, (1_700_000_000, 1_700_000_000))
        original_timestamp = obsidian_wiki.filesystem_timestamp(self.path)

        result = obsidian_wiki.add_frontmatter_to_document(
            self.config,
            "demo",
            "Wiki/demo/article.md",
            "Article",
            ["repair"],
        )

        frontmatter, body = obsidian_wiki.parse_frontmatter(self.path.read_text())
        self.assertEqual(result["path"], "Wiki/demo/article.md")
        self.assertEqual(frontmatter["title"], "Article")
        self.assertEqual(frontmatter["project"], "demo")
        self.assertEqual(frontmatter["tags"], ["wiki", "project/demo", "repair"])
        self.assertEqual(frontmatter["created"], frontmatter["updated"])
        self.assertEqual(frontmatter["updated"], original_timestamp)
        self.assertEqual(body.strip(), "# Existing Title\n\nBody")

    def test_add_frontmatter_rejects_document_with_existing_frontmatter(self) -> None:
        self.path.write_text(
            "---\n"
            "title: Article\n"
            "---\n\n"
            "# Article\n"
        )

        with self.assertRaisesRegex(obsidian_wiki.WikiError, "already has frontmatter"):
            obsidian_wiki.add_frontmatter_to_document(
                self.config,
                "demo",
                "Wiki/demo/article.md",
                None,
                None,
            )


if __name__ == "__main__":
    unittest.main()
