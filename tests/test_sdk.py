"""Tests for the public embedding API."""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fda.runtime import REPO_ROOT
from fda.sdk import Client, Config, EventBus, WebhookSink

from .test_bundles import make_bundle


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state.db"
        env = mock.patch.dict(os.environ, {"FDA_STATE": str(self.state)})
        env.start()
        self.addCleanup(env.stop)

    def client(self, **kwargs):
        options = {"state_path": str(self.state), "include_examples": True,
                   "audit_path": str(self.root / "audit.jsonl")}
        options.update(kwargs)
        return Client.create(Config(**options))

    def approve(self, client, plan, approver="human"):
        approvals = {}
        for step in plan["steps"]:
            if step["approval_id"]:
                client.grant_approval(step["approval_id"], approver)
                approvals[step["id"]] = step["approval_id"]
        return approvals

    def test_create_plan_run_and_status(self):
        client = self.client(tenant="acme", actor="alice")
        plan = client.plan("onboarding", {"role": "support"})
        approvals = self.approve(client, plan)
        result = client.run("onboarding", approvals, {"role": "support"})
        self.assertTrue(result.ok)
        self.assertEqual(result.tenant, "acme")
        self.assertEqual(client.status(result.run_id).status, "complete")
        self.assertIn("onboarding", [p["id"] for p in client.list_plays()["plays"]])

    def test_events_are_isolated_and_tenancy_scoped(self):
        client = self.client()
        seen = []

        def broken(event):
            raise RuntimeError("subscriber failed")

        client.on("approval.requested", lambda event: seen.append(event))
        client.on("approval.requested", broken)
        scoped = client.as_tenant("beta", actor="bob")
        scoped.plan("onboarding")

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].tenant, "beta")
        self.assertEqual(seen[0].actor, "bob")
        self.assertTrue(any("subscriber failed" in row["error"]
                            for row in client.events.errors))

    def test_external_approval_flow(self):
        client = self.client(approval_mode="external")
        plan = client.plan("onboarding")
        approval_id = next(step["approval_id"] for step in plan["steps"]
                           if step["approval_id"])
        with self.assertRaises(Exception):
            client.runtime.approvals.grant(approval_id, "model")
        self.assertEqual(client.approval_status(approval_id)["granted"], False)
        approvals = self.approve(client, plan)
        result = client.run("onboarding", approvals)
        self.assertTrue(result.ok)

    def test_custom_connector_handler(self):
        playbooks = self.root / "playbooks"
        playbooks.mkdir()
        (playbooks / "ping.json").write_text(json.dumps({
            "id": "ping", "name": "Ping", "description": "SDK test",
            "purpose": "sdk test", "steps": [{
                "id": "check", "title": "Ping", "tool": "connectors.call",
                "connector": "custom", "action": "custom.status",
                "scopes": ["read"], "needs": ["aggregate"],
            }],
        }), encoding="utf-8")
        client = Client.from_paths(
            playbooks, state_path=str(self.state), audit_path=str(self.root / "audit.jsonl"),
            connectors_path=str(REPO_ROOT / "examples" / "connectors.json"),
        )
        client.register_connector("custom", "Custom", ["read"], ["custom.status"],
                                  handler=lambda ctx: {"alive": True})
        result = client.run("ping")
        self.assertTrue(result.ok)
        payload = result.results[0]["result"]
        self.assertEqual(payload["mode"], "adapter")
        self.assertTrue(payload["alive"])

    def test_webhook_signature_and_delivery(self):
        received = []

        class SinkHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received.append((self.rfile.read(length),
                                 self.headers.get("X-FDA-Signature", "")))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SinkHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]

        bus = EventBus()
        sink = WebhookSink("http://127.0.0.1:%d/hook" % port, secret="shared",
                           events=["test.event"], bus=bus)
        bus.emit("test.event", {"hello": "world"})
        # No sleep: the POST is synchronous.
        self.assertEqual(len(received), 1)
        body, signature = received[0]
        expected = "sha256=" + hmac.new(b"shared", body, hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(sink.delivered, 1)
        self.assertEqual(json.loads(body)["payload"]["hello"], "world")

    def test_install_agent_from_archive(self):
        source = make_bundle(self.root / "source", "acme.sdk-agent")
        from fda.bundle import build_bundle
        archive = build_bundle(source, self.root / "sdk.fda")
        client = self.client(store=str(self.root / "store"))
        installed = client.install_agent(archive)
        self.assertEqual(installed["id"], "acme.sdk-agent")
        reloaded = self.client(store=str(self.root / "store"))
        self.assertIn("acme.sdk-agent", [row["id"] for row in
                                         reloaded.list_agents()["agents"]])

    def test_ops_and_audit_helpers(self):
        client = self.client(tenant="acme")
        self.assertFalse(client.ops_status()["kill_switch"]["paused"])
        client.pause("acme", "maintenance")
        result = client.run("access_review")
        self.assertEqual(result.status, "denied")
        client.resume("acme")
        self.assertTrue(client.run("access_review").ok)
        self.assertTrue(client.verify_audit()["ok"])
        self.assertGreater(client.audit(10)["entries"], 0)


if __name__ == "__main__":
    unittest.main()
