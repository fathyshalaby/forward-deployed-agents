import unittest

from fda.plays import Playbook, PlayError, load_playbooks
from fda.runtime import DEFAULT_PLAYBOOKS

from .helpers import fresh_runtime, run_play, tool_result


class PlayTests(unittest.TestCase):
    def setUp(self):
        self.runtime = fresh_runtime()

    def test_loads_example_playbooks(self):
        books = load_playbooks(DEFAULT_PLAYBOOKS)
        self.assertEqual(set(books), {
            "onboarding", "support_fix", "access_review", "content_lookup",
        })

    def test_play_plan_issues_approval_ids(self):
        plan = self.runtime.engine.plan("onboarding")
        approvals = [step["approval_id"] for step in plan["steps"] if step["approval_id"]]
        self.assertEqual(len(approvals), 2)
        self.assertEqual(len(set(approvals)), 2)

    def test_run_without_approvals_is_denied(self):
        run = self.runtime.engine.run("onboarding")
        self.assertEqual(run["status"], "denied")
        self.assertEqual(run["denied_step"], "welcome_ticket")

    def test_run_with_approvals_completes(self):
        run = run_play(self.runtime, "onboarding")
        self.assertEqual(run["status"], "complete")
        self.assertTrue(all(step["ok"] for step in run["results"]))

    def test_approval_is_single_use(self):
        plan = self.runtime.engine.plan("onboarding")
        approval_id = plan["steps"][1]["approval_id"]
        self.runtime.approvals.grant(approval_id, "test-human")
        self.runtime.engine.run("onboarding", {"welcome_ticket": approval_id,
                                                "announce": self.runtime.approvals.request(
                                                    "play.run.onboarding.announce", "test",
                                                    ["metadata"], "customer onboarding")["approval_id"]})
        with self.assertRaises(Exception):
            self.runtime.approvals.consume(approval_id, "play.run.onboarding.welcome_ticket",
                                           ["metadata"], "customer onboarding")

    def test_privacy_check_content_step(self):
        check = self.runtime.engine.privacy_check("content_lookup", "search")
        self.assertEqual(check["needs"], ["content"])
        self.assertTrue(check["approval_required"])
        self.assertFalse(check["default_allowed"])

    def test_status_roundtrip(self):
        run = run_play(self.runtime, "access_review")
        status = self.runtime.engine.status(run["run_id"])
        self.assertEqual(status["play"], "access_review")

    def test_duplicate_step_ids_rejected(self):
        raw = {
            "id": "bad", "purpose": "test",
            "steps": [{"id": "same", "tool": "note"}, {"id": "same", "tool": "note"}],
        }
        with self.assertRaises(PlayError):
            Playbook.from_dict(raw)

    def test_tool_surface_reports_plays(self):
        payload = tool_result(self.runtime, "plays.list")
        self.assertIn("support_fix", [play["id"] for play in payload["plays"]])


if __name__ == "__main__":
    unittest.main()
