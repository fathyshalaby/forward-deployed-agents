"""Generic MCP tools exposed by the framework."""
from typing import Dict, List

from .plays import PlayError

TOOL_VERSION = "0.1.0"


class ToolError(Exception):
    """Expected, user-facing tool failure."""


def _obj(properties=None, required=None):
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def _str(description):
    return {"type": "string", "description": description}


def connectors_list(runtime, args):
    return {"connectors": runtime.connectors.list_public()}


def plays_list(runtime, args):
    return {"plays": runtime.engine.list()}


def play_describe(runtime, args):
    return runtime.engine.describe(args["play_id"])


def play_plan(runtime, args):
    return runtime.engine.plan(args["play_id"], args.get("context", {}))


def play_run(runtime, args):
    return runtime.engine.run(
        args["play_id"], args.get("approvals", {}), args.get("context", {})
    )


def play_status(runtime, args):
    return runtime.engine.status(args["run_id"])


def play_privacy_check(runtime, args):
    return runtime.engine.privacy_check(args["play_id"], args["step_id"])


def approval_request(runtime, args):
    return runtime.approvals.request(
        action=args["action"],
        reason=args["reason"],
        needs=args["needs"],
        purpose=args["purpose"],
    )


def approval_grant(runtime, args):
    return runtime.approvals.grant(args["approval_id"], args["approver"])


def audit_explain(runtime, args):
    return runtime.audit.explain(args.get("limit", 30))


TOOLS: List[dict] = [
    {
        "name": "connectors.list",
        "description": "List the connectors the user granted, with scopes and actions. No credentials or endpoints are exposed.",
        "inputSchema": _obj(),
        "handler": connectors_list,
    },
    {
        "name": "plays.list",
        "description": "List available playbooks. Each playbook is a reusable workflow definition supplied by the customer or framework operator.",
        "inputSchema": _obj(),
        "handler": plays_list,
    },
    {
        "name": "play.describe",
        "description": "Show the steps, data classes, scopes and approval gates of one playbook before running anything.",
        "inputSchema": _obj({"play_id": _str("Playbook id")}, ["play_id"]),
        "handler": play_describe,
    },
    {
        "name": "play.plan",
        "description": "Prepare a playbook run and issue single-use approval requests for gated steps. Executes nothing.",
        "inputSchema": _obj({
            "play_id": _str("Playbook id"),
            "context": {"type": "object", "description": "Optional non-sensitive context"},
        }, ["play_id"]),
        "handler": play_plan,
    },
    {
        "name": "play.run",
        "description": "Execute a playbook. Pass approvals as a map of step id to approval id. Fails closed on the first policy denial.",
        "inputSchema": _obj({
            "play_id": _str("Playbook id"),
            "approvals": {"type": "object", "description": "step id -> approval id"},
            "context": {"type": "object", "description": "Optional non-sensitive context"},
        }, ["play_id"]),
        "handler": play_run,
    },
    {
        "name": "play.status",
        "description": "Return the recorded result of a previous playbook run.",
        "inputSchema": _obj({"run_id": _str("Run id")}, ["run_id"]),
        "handler": play_status,
    },
    {
        "name": "play.privacy_check",
        "description": "Dry-run one step: show which data classes, scopes and approvals it needs without consuming an approval.",
        "inputSchema": _obj({
            "play_id": _str("Playbook id"),
            "step_id": _str("Step id"),
        }, ["play_id", "step_id"]),
        "handler": play_privacy_check,
    },
    {
        "name": "approval.request",
        "description": "Create a human approval request for an action outside the default data budget.",
        "inputSchema": _obj({
            "action": _str("Action name the approval is bound to"),
            "reason": _str("Why the action is needed"),
            "needs": {"type": "array", "items": _str("Data class"), "description": "aggregate, metadata, identifier or content"},
            "purpose": _str("Stated purpose"),
        }, ["action", "reason", "needs", "purpose"]),
        "handler": approval_request,
    },
    {
        "name": "approval.grant",
        "description": "DEMO ONLY: simulate a human granting an approval. Replace with your customer approval UI in production.",
        "inputSchema": _obj({
            "approval_id": _str("Approval id"),
            "approver": _str("Name or role of the human approver"),
        }, ["approval_id", "approver"]),
        "handler": approval_grant,
    },
    {
        "name": "audit.explain",
        "description": "Explain what the agent did, which connectors it used and which approvals it consumed. Free text appears only as a hash.",
        "inputSchema": _obj({
            "limit": {"type": "integer", "description": "How many recent entries to show"}
        }),
        "handler": audit_explain,
    },
]


def tool_catalog() -> List[dict]:
    return [
        {key: value for key, value in tool.items() if key != "handler"}
        for tool in TOOLS
    ]


def call_tool(runtime, name: str, arguments: dict) -> dict:
    for tool in TOOLS:
        if tool["name"] == name:
            try:
                return tool["handler"](runtime, arguments or {})
            except (ToolError, PlayError, KeyError, TypeError) as exc:
                raise ToolError(str(exc))
    raise ToolError("unknown tool: %s" % name)
