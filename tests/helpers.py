import json

from fda.runtime import load_runtime


def fresh_runtime():
    return load_runtime(persist_audit=False)


def run_play(runtime, play_id, grant=True):
    plan = runtime.engine.plan(play_id)
    approvals = {}
    if grant:
        for step in plan["steps"]:
            if step["approval_id"]:
                runtime.approvals.grant(step["approval_id"], "test-human")
                approvals[step["id"]] = step["approval_id"]
    return runtime.engine.run(play_id, approvals)


def rpc(runtime, method, params=None, msg_id=1):
    from fda.mcp import MCPServer
    message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return MCPServer(runtime).handle(message)


def tool_result(runtime, name, arguments=None, msg_id=1):
    response = rpc(runtime, "tools/call",
                   {"name": name, "arguments": arguments or {}}, msg_id)
    return json.loads(response["result"]["content"][0]["text"])
