"""Minimal MCP server over stdio using only the Python standard library.

JSON-RPC 2.0, one JSON message per line. Protocol traffic goes to stdout;
diagnostics go to stderr, so the server composes cleanly with any MCP client.
"""
import json
import sys

from . import __version__
from .tools import TOOL_VERSION, ToolError, call_tool, tool_catalog

PROTOCOL_VERSION = "2024-11-05"


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


class MCPServer:
    def __init__(self, runtime):
        self.runtime = runtime

    def handle(self, message):
        if not isinstance(message, dict):
            return _error(None, -32600, "invalid request")
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {})
        notification = "id" not in message

        if method and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "forward-deployed-agents", "version": __version__},
                    "instructions": (
                        "Use agents.list to see installed agents, then plays.list "
                        "and play.describe before acting. Prefer play.plan, then "
                        "human approval (out-of-band in external mode), then "
                        "play.run. Audit every run."
                    ),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tool_catalog()}
            elif method == "tools/call":
                return self._call(msg_id, params)
            elif method == "resources/list":
                result = {"resources": []}
            elif method == "prompts/list":
                result = {"prompts": []}
            elif method is None:
                return _error(msg_id, -32600, "missing method")
            else:
                return _error(msg_id, -32601, "method not found: %s" % method)
        except (TypeError, ValueError) as exc:
            return _error(msg_id, -32602, "invalid params: %s" % exc)

        if notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _call(self, msg_id, params):
        if not isinstance(params, dict):
            return _error(msg_id, -32602, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(msg_id, -32602, "name and arguments are required")
        try:
            payload = call_tool(self.runtime, name, arguments)
            content = [{"type": "text", "text": json.dumps(payload, sort_keys=True)}]
            result = {"content": content}
        except ToolError as exc:
            content = [{"type": "text", "text": str(exc)}]
            result = {"content": content, "isError": True}
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def stdio_loop(runtime, inp=None, out=None, err=None):
    inp = inp or sys.stdin
    out = out or sys.stdout
    err = err or sys.stderr
    server = MCPServer(runtime)
    for line in inp:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
        else:
            response = server.handle(message)
        if response is not None:
            out.write(json.dumps(response, separators=(",", ":")) + "\n")
            out.flush()
        else:
            err.write("notification ignored\n")
            err.flush()
    return 0
