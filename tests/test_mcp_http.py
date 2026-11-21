"""Tests for the HTTP/SSE MCP transport used by ChatGPT and remote clients."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from fda.mcp_http import create_server
from fda.runtime import load_agents_runtime


class MCPHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"FDA_STATE": str(root / "env-state.db")})
        env.start()
        self.addCleanup(env.stop)
        runtime = load_agents_runtime(
            include_examples=True,
            state_path=str(root / "state.db"),
            audit_path=str(root / "audit.jsonl"),
            approval_mode="external",
        )
        self.server = create_server(runtime, "127.0.0.1", 0, token="mcp-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def request(self, path, body=None, token="mcp-token", accept="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read().decode(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode(), dict(exc.headers)

    def rpc(self, message, **kwargs):
        status, text, headers = self.request("/mcp", message, **kwargs)
        return status, text, headers

    def test_health_is_public_and_authenticated_rpc_works(self):
        status, text, _ = self.request("/health", token="")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["transport"], "http/sse")
        status, text, _ = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["result"], {})
        status, text, _ = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   token="wrong")
        self.assertEqual(status, 401)

    def test_tools_list_has_safety_annotations(self):
        _, text, _ = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {row["name"]: row for row in json.loads(text)["result"]["tools"]}
        self.assertEqual(len(tools), 17)
        self.assertTrue(tools["plays.list"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["artifacts.list"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["play.run"]["annotations"]["destructiveHint"])
        self.assertFalse(tools["play.run"]["annotations"]["readOnlyHint"])

    def test_sse_response_carries_json_rpc_message(self):
        status, text, headers = self.rpc(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            accept="application/json, text/event-stream")
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn("event: message", text)
        payload = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
        self.assertEqual(payload["id"], 7)

    def test_tools_call_over_http(self):
        _, text, _ = self.rpc({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "ops.status", "arguments": {}},
        })
        payload = json.loads(json.loads(text)["result"]["content"][0]["text"])
        self.assertEqual(payload["approval_mode"], "external")

    def test_batch_and_notifications(self):
        status, text, _ = self.rpc([
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["id"], 3)


if __name__ == "__main__":
    unittest.main()
