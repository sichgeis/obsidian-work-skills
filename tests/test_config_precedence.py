from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIKI_SCRIPT = ROOT / "scripts" / "obsidian_wiki.py"
GLOSSARY_SCRIPT = ROOT / "scripts" / "obsidian_glossary.py"
WORK_TASKS_SCRIPT = ROOT / "scripts" / "obsidian_work_tasks.py"


class ConfigPrecedenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / ".agents").mkdir()
        (self.project / ".codex").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_doctor(self, script: Path) -> dict[str, object]:
        env = os.environ.copy()
        env.pop("OBSIDIAN_VAULT_PATH", None)
        result = subprocess.run(
            [sys.executable, str(script), "doctor"],
            cwd=self.project,
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_codex_wiki_config_overrides_legacy_agents_config(self) -> None:
        agents_vault = self.root / "agents-vault"
        codex_vault = self.root / "codex-vault"
        (self.project / ".agents" / "obsidian-wiki.json").write_text(json.dumps({"vault_path": str(agents_vault), "wiki_dir": "AgentsWiki"}))
        (self.project / ".codex" / "obsidian-wiki.json").write_text(json.dumps({"vault_path": str(codex_vault), "wiki_dir": "CodexWiki"}))

        payload = self.run_doctor(WIKI_SCRIPT)

        self.assertEqual(payload["vault_path"], str(codex_vault.resolve()))
        self.assertEqual(payload["wiki_dir"], "CodexWiki")

    def test_codex_glossary_config_overrides_legacy_agents_config(self) -> None:
        agents_vault = self.root / "agents-vault"
        codex_vault = self.root / "codex-vault"
        (self.project / ".agents" / "obsidian-glossary.json").write_text(json.dumps({"vault_path": str(agents_vault), "glossary_dir": "AgentsGlossary"}))
        (self.project / ".codex" / "obsidian-glossary.json").write_text(json.dumps({"vault_path": str(codex_vault), "glossary_dir": "CodexGlossary"}))

        payload = self.run_doctor(GLOSSARY_SCRIPT)

        self.assertEqual(payload["vault_path"], str(codex_vault.resolve()))
        self.assertEqual(payload["glossary_dir"], "CodexGlossary")

    def test_codex_work_tasks_config_overrides_legacy_agents_config(self) -> None:
        agents_vault = self.root / "agents-vault"
        codex_vault = self.root / "codex-vault"
        (self.project / ".agents" / "obsidian-work-tasks.json").write_text(json.dumps({"vault_path": str(agents_vault), "tasks_dir": "AgentsTasks"}))
        (self.project / ".codex" / "obsidian-work-tasks.json").write_text(json.dumps({"vault_path": str(codex_vault), "tasks_dir": "CodexTasks"}))

        payload = self.run_doctor(WORK_TASKS_SCRIPT)

        self.assertEqual(payload["vault_path"], str(codex_vault.resolve()))
        self.assertEqual(payload["tasks_dir"], "CodexTasks")


if __name__ == "__main__":
    unittest.main()
