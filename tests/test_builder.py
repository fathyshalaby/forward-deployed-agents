"""Tests for the single meta-skill and its language-agnostic contract."""
import io
import json
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from fda import cli
from fda.builder_skill import BUILDER_SKILL

ROOT = Path(__file__).resolve().parents[1]


class BuilderSkillTests(unittest.TestCase):
    def test_default_skill_command_prints_meta_skill(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.cmd_meta_skill(None), 0)
        self.assertEqual(out.getvalue(), BUILDER_SKILL)
        self.assertIn("name: fda-agent-builder", out.getvalue())

    def test_fda_skill_needs_no_subcommand(self):
        args = cli.build_parser().parse_args(["skill"])
        self.assertEqual(args.func, cli.cmd_meta_skill)
        args = cli.build_parser().parse_args(["meta"])
        self.assertEqual(args.func, cli.cmd_meta_skill)

    def test_generated_files_stay_in_sync(self):
        for relative in (
            "skills/fda-agent-builder/SKILL.md",
            "plugins/fda-claude/skills/fda-agent-builder/SKILL.md",
        ):
            self.assertEqual((ROOT / relative).read_text(), BUILDER_SKILL)
        self.assertIn(BUILDER_SKILL, (ROOT / "docs/builder_prompt.md").read_text())

    def test_uploadable_skill_contains_only_the_meta_skill(self):
        with zipfile.ZipFile(ROOT / "integrations/fda-skill.zip") as archive:
            names = set(archive.namelist())
            text = archive.read("fda-agent-builder/SKILL.md").decode()
        self.assertEqual(names, {"fda-agent-builder/SKILL.md"})
        self.assertEqual(text, BUILDER_SKILL)

    def test_plugin_has_one_skill(self):
        skills = ROOT / "plugins/fda-claude/skills"
        self.assertEqual([p.name for p in sorted(skills.iterdir())],
                         ["fda-agent-builder"])
        manifest = json.loads(
            (ROOT / "plugins/fda-claude/.claude-plugin/plugin.json").read_text())
        self.assertIn("coding agent", manifest["description"])

    def test_meta_skill_is_language_agnostic(self):
        for phrase in ("any language", "FDA_HANDLERS", "webhook", "X-FDA-Signature",
                       "claude code", "codex", "fda api serve", "docs/boilerplate.md"):
            self.assertIn(phrase, BUILDER_SKILL.lower()
                          if phrase.islower() else BUILDER_SKILL)

    def test_boilerplate_contract_is_present(self):
        text = (ROOT / "docs/boilerplate.md").read_text()
        for phrase in ("FDA_HANDLERS", "X-FDA-Tenant", "POST /v1/plans",
                       "POST /v1/runs", "X-FDA-Signature", "Definition of done"):
            self.assertIn(phrase, text)

    def test_readme_leads_with_the_meta_skill(self):
        text = (ROOT / "README.md").read_text()
        lowered = text.lower()
        self.assertLess(lowered.index("give this to claude code or codex"),
                        lowered.index("production in one block"))
        self.assertIn("fda skill", text)


if __name__ == "__main__":
    unittest.main()
