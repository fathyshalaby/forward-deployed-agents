import io
import json
import unittest

from fda.mcp import MCPServer, stdio_loop

from .helpers import fresh_runtime


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.runtime = fresh_runtime()
        self.server = MCPServer(self.runtime)

    def test_initialize_returns_server_info(self):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(response["result"]["serverInfo"]["name"],
                         "forward-deployed-agents")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_ping(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(response["result"], {})

    def test_tools_list_covers_control_plane_and_bundles(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(len(names), 17)
        for name in ("plays.list", "play.run", "approval.grant", "approval.status",
                     "audit.explain", "agents.list", "agent.describe", "agent.skill",
                     "artifacts.list", "artifacts.get", "ops.status"):
            self.assertIn(name, names)

    def test_tools_call_wraps_json_content(self):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "plays.list", "arguments": {}},
        })
        content = response["result"]["content"][0]
        self.assertEqual(content["type"], "text")
        self.assertIn("onboarding", content["text"])

    def test_tool_error_is_iserror(self):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "play.describe", "arguments": {"play_id": "nope"}},
        })
        self.assertTrue(response["result"]["isError"])
        self.assertIn("unknown playbook", response["result"]["content"][0]["text"])

    def test_unknown_method_is_protocol_error(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 6, "method": "nope"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_notification_has_no_response(self):
        result = self.server.handle({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        self.assertIsNone(result)

    def test_stdio_loop_emits_one_line_per_request(self):
        payload = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "not json",
        ]) + "\n"
        out, err = io.StringIO(), io.StringIO()
        stdio_loop(self.runtime, io.StringIO(payload), out, err)
        lines = [line for line in out.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("-32700", lines[1])


if __name__ == "__main__":
    unittest.main()
