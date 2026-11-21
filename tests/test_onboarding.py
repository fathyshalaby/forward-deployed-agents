"""Tests for the copy-paste onboarding engineer skill."""
import io
import json
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from fda import cli
from fda.onboarding_skill import ONBOARDING_SKILL

ROOT = Path(__file__).resolve().parents[1]


class OnboardingSkillTests(unittest.TestCase):
    def test_cli_prints_the_skill(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.cmd_skill_onboarding(None), 0)
        self.assertEqual(out.getvalue(), ONBOARDING_SKILL)
        self.assertIn("name: fda-onboarding-engineer", out.getvalue())

    def test_skill_files_and_prompt_stay_in_sync(self):
        for relative in (
            "skills/fda-onboarding-engineer/SKILL.md",
            "plugins/fda-claude/skills/fda-onboarding-engineer/SKILL.md",
        ):
            self.assertEqual((ROOT / relative).read_text(), ONBOARDING_SKILL)
        prompt = (ROOT / "docs/onboarding_prompt.md").read_text()
        self.assertIn(ONBOARDING_SKILL, prompt)
        self.assertIn("copy", prompt.lower())

    def test_skill_covers_the_full_onboarding_loop(self):
        for phrase in ("Phase 0", "Phase 9", "fda agents build", "--pin",
                       "FDA_APPROVAL_MODE=external", "approval.grant",
                       "fda ops audit-verify", "Add custom MCP server",
                       "Stop conditions", "Handoff record"):
            self.assertIn(phrase, ONBOARDING_SKILL)

    def test_uploadable_zip_has_both_skills(self):
        archive = ROOT / "integrations/fda-skill.zip"
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn("fda-forward-deployed-agents/SKILL.md", names)
        self.assertIn("fda-onboarding-engineer/SKILL.md", names)

    def test_plugin_manifest_is_valid_json(self):
        manifest = ROOT / "plugins/fda-claude/.claude-plugin/plugin.json"
        data = json.loads(manifest.read_text())
        self.assertEqual(data["version"].split(".")[0], "0")
        self.assertIn("fda", data["name"])


if __name__ == "__main__":
    unittest.main()
