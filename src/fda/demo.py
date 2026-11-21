"""Scripted, deterministic demo of the generic framework.

Run: python3 -m fda.demo
"""
import json

from .mcp import MCPServer
from .runtime import load_runtime


def _show(title, payload):
    print("\n== %s ==" % title)
    print(json.dumps(payload, indent=2, sort_keys=True))


def main():
    runtime = load_runtime(persist_audit=False)
    server = MCPServer(runtime)
    counter = [0]

    protocol_methods = {"initialize", "ping", "tools/list", "tools/call",
                        "resources/list", "prompts/list"}

    def call(method, params=None):
        counter[0] += 1
        if method in protocol_methods:
            message = {"jsonrpc": "2.0", "id": counter[0], "method": method}
            if params is not None:
                message["params"] = params
        else:
            message = {
                "jsonrpc": "2.0", "id": counter[0], "method": "tools/call",
                "params": {"name": method, "arguments": params or {}},
            }
        response = server.handle(message)
        result = response.get("result", response.get("error")) if response else None
        if isinstance(result, dict) and "content" in result:
            text = result["content"][0]["text"]
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"error": text, "isError": result.get("isError", False)}
        return result

    _show("initialize", call("initialize", {"protocolVersion": "2024-11-05"}))
    tools = call("tools/list")
    _show("tools/list (names)", {"tools": [t["name"] for t in tools["tools"]]})
    plays = call("plays.list")
    _show("plays.list (ids)", {"plays": [p["id"] for p in plays["plays"]]})

    _show("play.describe: onboarding", call("play.describe", {"play_id": "onboarding"}))
    plan = call("play.plan", {"play_id": "onboarding", "context": {"role": "support"}})
    _show("play.plan: approvals issued", {
        "steps": [
            {"id": s["id"], "approval_id": s["approval_id"]}
            for s in plan["steps"]
        ]
    })

    approvals = {}
    for step in plan["steps"]:
        if step["approval_id"]:
            call("approval.grant", {
                "approval_id": step["approval_id"],
                "approver": "demo-human",
            })
            approvals[step["id"]] = step["approval_id"]
    run = call("play.run", {"play_id": "onboarding", "approvals": approvals})
    _show("play.run: onboarding", {
        "run_id": run["run_id"],
        "status": run["status"],
        "steps": [
            {"step": r["step"], "ok": r["ok"],
             "action": r.get("result", {}).get("action", "note")}
            for r in run["results"]
        ],
    })

    _show("play.privacy_check: content step",
          call("play.privacy_check", {"play_id": "content_lookup", "step_id": "search"}))
    denied = call("play.run", {"play_id": "content_lookup"})
    _show("play.run: content without approval (fail closed)", {
        "status": denied["status"],
        "denied_step": denied["denied_step"],
        "error": denied["results"][0]["error"],
    })
    _show("audit.explain", call("audit.explain", {"limit": 12}))

    print("\nDemo done. For a shareable agent, run: python3 -m fda agents init ./my-agent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
