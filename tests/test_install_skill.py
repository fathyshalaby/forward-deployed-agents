"""Tests for the direct-from-GitHub skill installer."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import install_skill
from fda.builder_skill import BUILDER_SKILL

ROOT = Path(__file__).resolve().parents[1]


class InstallSkillTests(unittest.TestCase):
    def test_install_from_raw_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(install_skill, "download",
                                   return_value=BUILDER_SKILL.encode()):
                target = install_skill.install("https://example.invalid", Path(tmp))
            self.assertEqual(target, Path(tmp) / "fda-agent-builder" / "SKILL.md")
            self.assertEqual(target.read_text(), BUILDER_SKILL)

    def test_install_from_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("fda-agent-builder/SKILL.md", BUILDER_SKILL)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(install_skill, "download",
                                   return_value=buffer.getvalue()):
                target = install_skill.install("https://example.invalid",
                                               Path(tmp), source="zip")
            self.assertEqual(target.read_text(), BUILDER_SKILL)

    def test_rejects_wrong_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(install_skill, "download",
                                   return_value=b"not a skill"):
                with self.assertRaises(ValueError):
                    install_skill.install("https://example.invalid", Path(tmp))

    def test_docs_point_at_the_repo(self):
        repo = "https://github.com/fathyshalaby/forward-deployed-agents"
        readme = (ROOT / "README.md").read_text()
        install = (ROOT / "docs/install.md").read_text()
        self.assertIn(repo, readme)
        self.assertIn(repo, install)
        self.assertIn("raw.githubusercontent.com", install)
        self.assertIn("install_skill.py", install)


if __name__ == "__main__":
    unittest.main()
