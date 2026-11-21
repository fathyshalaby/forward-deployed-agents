"""Tests for the embedded end-to-end tutorial."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fda import cli
from fda.tutorial import TUTORIAL

ROOT = Path(__file__).resolve().parents[1]


class TutorialTests(unittest.TestCase):
    def test_cli_prints_tutorial(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.cmd_tutorial(None), 0)
        self.assertEqual(out.getvalue(), TUTORIAL)

    def test_doc_stays_in_sync(self):
        self.assertEqual((ROOT / "docs/tutorial.md").read_text(), TUTORIAL)

    def test_tutorial_covers_every_phase(self):
        for phrase in ("Install and check", "Author your own bundle",
                       "Package, sign", "Turn on real approvals",
                       "Wire your real product APIs", "Drive it from AI clients",
                       "Deploy it", "Verify and operate", "onboarding engineer",
                       "Troubleshooting"):
            self.assertIn(phrase, TUTORIAL)

    def test_tutorial_commands_are_real(self):
        for command in ("fda agents init", "fda agents validate",
                        "fda agents build", "fda keys generate",
                        "fda registry publish", "fda agents install",
                        "fda approvals serve", "fda api serve",
                        "fda serve --transport http", "fda ops audit-verify",
                        "fda ops pause", "fda skill onboarding"):
            self.assertIn(command, TUTORIAL)


if __name__ == "__main__":
    unittest.main()
