"""Generic MCP tools exposed by the framework."""
from typing import List

from .bundle import BundleError, bundle_skill_text, default_store, load_bundle_dir
from .connectors import ConnectorError
from .plays import PlayError
from .privacy import PrivacyError

TOOL_VERSION = "0.5.0"


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
    return runtime.approvals.grant(
        args["approval_id"], args["approver"], mode=runtime.approval_mode)


def approval_status(runtime, args):
    return runtime.approvals.status(args["approval_id"])


def ops_status(runtime, args):
    state = runtime.state
    return {
        "approval_mode": runtime.approval_mode,
        "tenant": runtime.tenant,
        "actor": runtime.actor,
        "state_path": str(state.path) if state else "",
        "kill_switch": state.kill_check(runtime.tenant) if state else {"paused": False},
        "stats": state.stats() if state else {},
        "audit_chain": state.audit_verify() if state else {"entries": 0, "ok": True},
    }


def audit_explain(runtime, args):
    return runtime.audit.explain(args.get("limit", 30))


def agents_list(runtime, args):
    return {
        "agents": runtime.bundles,
        "store": str(default_store()),
        "count": len(runtime.bundles),
    }


def _installed(runtime, identifier: str):
    for row in runtime.bundles:
        if row["id"] == identifier:
            return row
    raise ToolError("unknown agent: %s" % identifier)


def agent_describe(runtime, args):
    row = _installed(runtime, args["agent_id"])
    return {key: value for key, value in row.items() if key != "source"}


def agent_skill(runtime, args):
    row = _installed(runtime, args["agent_id"])
    bundle = load_bundle_dir(row["source"])
    return {
        "agent_id": row["id"],
        "name": row["name"],
        "skill": bundle_skill_text(
            bundle, prefer_custom=bool(args.get("prefer_custom", True))
        ),
    }


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
        "description": "Grant an approval in demo mode only. In FDA_APPROVAL_MODE=external this always fails; use the out-of-band approval UI or `fda approvals grant`.",
        "inputSchema": _obj({
            "approval_id": _str("Approval id"),
            "approver": _str("Name or role of the human approver"),
        }, ["approval_id", "approver"]),
        "handler": approval_grant,
    },
    {
        "name": "approval.status",
        "description": "Read the status and exact bindings of an approval request without changing it.",
        "inputSchema": _obj({"approval_id": _str("Approval id")}, ["approval_id"]),
        "handler": approval_status,
    },
    {
        "name": "ops.status",
        "description": "Report approval mode, tenant, kill switch state, counters and audit chain integrity.",
        "inputSchema": _obj(),
        "handler": ops_status,
    },
    {
        "name": "audit.explain",
        "description": "Explain what the agent did, which connectors it used and which approvals it consumed. Free text appears only as a hash.",
        "inputSchema": _obj({
            "limit": {"type": "integer", "description": "How many recent entries to show"}
        }),
        "handler": audit_explain,
    },
    {
        "name": "agents.list",
        "description": "List agent bundles installed on this server, with versions, playbooks and connectors.",
        "inputSchema": _obj(),
        "handler": agents_list,
    },
    {
        "name": "agent.describe",
        "description": "Describe one installed agent bundle without running anything.",
        "inputSchema": _obj({"agent_id": _str("Agent bundle id")}, ["agent_id"]),
        "handler": agent_describe,
    },
    {
        "name": "agent.skill",
        "description": "Return the AI skill markdown for an installed agent, ready to save into a client skills directory.",
        "inputSchema": _obj({
            "agent_id": _str("Agent bundle id"),
            "prefer_custom": {"type": "boolean", "description": "Use the bundle's own SKILL.md when present"},
        }, ["agent_id"]),
        "handler": agent_skill,
    },
]


READ_ONLY_TOOLS = {
    "connectors.list", "plays.list", "play.describe", "play.status",
    "play.privacy_check", "approval.status", "ops.status", "audit.explain",
    "agents.list", "agent.describe", "agent.skill",
}

DESTRUCTIVE_TOOLS = {"play.run", "approval.grant"}


def tool_catalog() -> List[dict]:
    catalog = []
    for tool in TOOLS:
        item = {key: value for key, value in tool.items() if key != "handler"}
        # MCP annotations: clients use these to decide whether to ask for
        # confirmation (ChatGPT treats anything without readOnlyHint as a write).
        item["annotations"] = {
            "readOnlyHint": tool["name"] in READ_ONLY_TOOLS,
            "destructiveHint": tool["name"] in DESTRUCTIVE_TOOLS,
            "openWorldHint": False,
        }
        catalog.append(item)
    return catalog


def call_tool(runtime, name: str, arguments: dict) -> dict:
    for tool in TOOLS:
        if tool["name"] == name:
            try:
                return tool["handler"](runtime, arguments or {})
            except (ToolError, PlayError, PrivacyError, ConnectorError,
                    BundleError, KeyError, TypeError, ValueError, OSError) as exc:
                raise ToolError(str(exc))
    raise ToolError("unknown tool: %s" % name)
