import unittest

from fda.connectors import ConnectorError
from fda.privacy import PrivacyError

from .helpers import fresh_runtime, run_play


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = fresh_runtime()

    def test_content_without_approval_is_denied(self):
        run = self.runtime.engine.run("content_lookup")
        self.assertEqual(run["status"], "denied")
        self.assertIn("sensitive data requires an approval id", run["results"][0]["error"])

    def test_content_with_approval_runs(self):
        run = run_play(self.runtime, "content_lookup")
        self.assertEqual(run["status"], "complete")

    def test_write_requires_approval_even_for_metadata(self):
        decision = self.runtime.privacy.check(
            tool="write", needs=["metadata"], purpose="test",
            connector_id="tickets", approval_id=None, write=True,
        )
        self.assertEqual(decision["decision"], "deny")

    def test_approval_bound_to_action_and_purpose(self):
        approval_id = self.runtime.approvals.request(
            "one", "test", ["metadata"], "purpose-a")["approval_id"]
        self.runtime.approvals.grant(approval_id, "test-human")
        with self.assertRaises(PrivacyError):
            self.runtime.approvals.consume(approval_id, "two", ["metadata"], "purpose-a")
        with self.assertRaises(PrivacyError):
            self.runtime.approvals.consume(approval_id, "one", ["metadata"], "purpose-b")

    def test_audit_never_contains_free_text_or_secrets(self):
        self.runtime.audit.record(
            "test", "allow", text="alice@example.com ghp_secrettoken1234",
            purpose="test",
        )
        blob = str(self.runtime.audit.entries[-1])
        self.assertNotIn("alice@example.com", blob)
        self.assertNotIn("ghp_secrettoken1234", blob)
        self.assertIn("text_hash", blob)

    def test_audit_explain_shape(self):
        run_play(self.runtime, "onboarding")
        explained = self.runtime.audit.explain()
        self.assertGreater(explained["entries"], 0)
        self.assertIn("timeline", explained)
        self.assertTrue(all("decision" in row for row in explained["timeline"]))

    def test_unknown_connector_rejected(self):
        with self.assertRaises(ConnectorError):
            self.runtime.connectors.get("missing")

    def test_ungranted_action_rejected(self):
        with self.assertRaises(ConnectorError):
            self.runtime.connectors.call("observability", "tickets.create", scopes=["read"])

    def test_ungranted_scope_rejected(self):
        with self.assertRaises(ConnectorError):
            self.runtime.connectors.call("observability", "observability.get_metrics",
                                         scopes=["write"])


if __name__ == "__main__":
    unittest.main()
