"""Tests for the JSON HTTP adapter used by external products."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from fda.http_api import create_server
from fda.sdk import Client, Config


class HTTPAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"FDA_STATE": str(root / "env-state.db")})
        env.start()
        self.addCleanup(env.stop)
        self.client = Client.create(Config(
            state_path=str(root / "state.db"), include_examples=True,
            audit_path=str(root / "audit.jsonl"), tenant="acme", actor="alice",
        ))
        self.server = create_server(self.client, "127.0.0.1", 0,
                                    token="product-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.base = "http://127.0.0.1:%d/v1" % self.server.server_address[1]

    def request(self, path, method="GET", body=None, token="product-token",
                headers=None):
        payload = json.dumps(body or {}).encode() if body is not None else None
        request_headers = {"Content-Type": "application/json"}
        if token:
            request_headers["Authorization"] = "Bearer " + token
        request_headers.update(headers or {})
        request = urllib.request.Request(self.base + path, data=payload,
                                         headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_health_needs_no_token_but_api_does(self):
        with urllib.request.urlopen(self.base + "/health") as response:
            self.assertEqual(response.status, 200)
        status, payload = self.request("/plays", token="wrong")
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_discovery_and_plan_run_flow(self):
        status, payload = self.request("/plays")
        self.assertEqual(status, 200)
        self.assertIn("onboarding", [row["id"] for row in payload["plays"]])

        status, plan = self.request("/plans", "POST", {"play_id": "onboarding"})
        self.assertEqual(status, 201)
        approvals = {}
        for step in plan["steps"]:
            if step["approval_id"]:
                status, granted = self.request(
                    "/approvals/%s/grant" % step["approval_id"], "POST",
                    {"approver": "api-human"})
                self.assertEqual(status, 200)
                self.assertEqual(granted["status"], "granted")
                approvals[step["id"]] = step["approval_id"]

        status, run = self.request("/runs", "POST", {
            "play_id": "onboarding", "approvals": approvals})
        self.assertEqual(status, 201)
        self.assertEqual(run["status"], "complete")
        status, stored = self.request("/runs/" + run["run_id"])
        self.assertEqual(status, 200)
        self.assertEqual(stored["status"], "complete")

    def test_tenant_headers_scope_audit_and_audit_is_readable(self):
        headers = {"X-FDA-Tenant": "beta", "X-FDA-Actor": "bob"}
        status, run = self.request("/runs", "POST", {"play_id": "access_review"},
                                   headers=headers)
        self.assertEqual(status, 201)
        self.assertEqual(run["tenant"], "beta")
        status, payload = self.request("/audit?limit=50")
        self.assertEqual(status, 200)
        self.assertTrue(any(row.get("tenant") == "beta"
                            for row in payload["timeline"]))

    def test_ops_and_events(self):
        status, payload = self.request("/ops/pause", "POST",
                                       {"scope": "acme", "reason": "test"})
        self.assertEqual(status, 200)
        status, payload = self.request("/runs", "POST", {"play_id": "access_review"})
        self.assertEqual(status, 403)
        self.assertIn("kill switch", payload["results"][0]["error"])
        status, payload = self.request("/events")
        self.assertEqual(status, 200)
        self.assertTrue(any(event["name"] == "run.denied"
                            for event in payload["events"]))
        self.request("/ops/resume", "POST", {"scope": "acme"})

    def test_invalid_play_returns_client_error(self):
        status, payload = self.request("/plans", "POST", {"play_id": "missing"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
