import unittest
from pathlib import Path

from fda.runtime import REPO_ROOT

from .helpers import fresh_runtime, tool_result


class SkillAndDocsTests(unittest.TestCase):
    def test_skill_has_frontmatter(self):
        text = (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: forward-deployed-agents", text)
        self.assertIn("description:", text)

    def test_skill_states_non_negotiables(self):
        text = (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("Plan before acting", "Every write needs a human",
                       "Fail closed", "No content in the audit trail"):
            self.assertIn(phrase, text)

    def test_docs_exist(self):
        for name in ("chatgpt_and_claude", "builder_prompt", "boilerplate",
                     "install", "tutorial", "faq", "deployment", "security",
                     "integrating", "artifacts"):
            self.assertTrue((REPO_ROOT / "docs" / ("%s.md" % name)).exists())
        for gone in ("architecture", "playbook_authoring", "privacy_model",
                     "mcp_tools", "rollout", "from_enron_case", "agent_bundles",
                     "connect_an_ai", "deep_dive"):
            self.assertFalse((REPO_ROOT / "docs" / ("%s.md" % gone)).exists())

    def test_no_credential_fields_in_connector_descriptors(self):
        payload = tool_result(fresh_runtime(), "connectors.list")
        blob = str(payload)
        for forbidden in ("password", "token", "api_key", "http://", "https://"):
            self.assertNotIn(forbidden, blob.lower())


if __name__ == "__main__":
    unittest.main()
