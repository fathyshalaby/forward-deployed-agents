"""Minimal example of embedding an agent inside a product backend.

Run from the repository root:

    PYTHONPATH=src:. python3 examples/integrations/product_app.py

It uses a temporary playbook and a real Python handler instead of the built-in
simulated connectors, then shows how a product grants the approval and reads
the audit trail. Nothing here requires MCP or an AI client.
"""
import json
import tempfile
from pathlib import Path

from fda.sdk import Client


PLAYBOOK = {
    "id": "support_triage",
    "name": "Triage a support ticket",
    "description": "Read an aggregate signal and open an approved ticket.",
    "purpose": "triage an inbound support ticket",
    "steps": [
        {
            "id": "signal",
            "title": "Read the error rate",
            "tool": "connectors.call",
            "connector": "observability",
            "action": "observability.get_metrics",
            "scopes": ["read"],
            "needs": ["aggregate"],
        },
        {
            "id": "open_ticket",
            "title": "Open the follow-up ticket",
            "tool": "connectors.call",
            "connector": "tickets",
            "action": "tickets.create",
            "scopes": ["read", "write"],
            "needs": ["metadata"],
            "write": True,
        },
    ],
}

CONNECTORS = [
    {"id": "observability", "name": "Observability", "scopes": ["read"],
     "actions": ["observability.get_metrics"], "approval_required": []},
    {"id": "tickets", "name": "Ticket system", "scopes": ["read", "write"],
     "actions": ["tickets.create"], "approval_required": ["tickets.create"]},
]


def main():
    with tempfile.TemporaryDirectory(prefix="fda-product-") as tmp:
        root = Path(tmp)
        playbooks = root / "playbooks"
        playbooks.mkdir()
        (playbooks / "support_triage.json").write_text(json.dumps(PLAYBOOK))
        connectors = root / "connectors.json"
        connectors.write_text(json.dumps(CONNECTORS))

        client = Client.from_paths(
            playbooks, connectors_path=connectors,
            state_path=str(root / "state.db"),
            audit_path=str(root / "audit.jsonl"),
            approval_mode="external",
        )

        # Product-side adapter: real code, no credentials exposed to the agent.
        client.register_handler(
            "tickets.create",
            lambda ctx: {"created": True, "ref": "SUP-1042"},
        )

        notifications = []
        client.on("approval.requested", lambda event: notifications.append(event))

        scoped = client.as_tenant("customer-42", actor="support-app")
        plan = scoped.plan("support_triage", {"ticket": "INC-42"})
        approvals = {}
        for step in plan["steps"]:
            if step["approval_id"]:
                # In a real product this happens after an authenticated human
                # clicks Approve in your own UI.
                scoped.grant_approval(step["approval_id"], "alice@example.com")
                approvals[step["id"]] = step["approval_id"]

        result = scoped.run("support_triage", approvals, {"ticket": "INC-42"})
        print(json.dumps({
            "status": result.status,
            "run_id": result.run_id,
            "results": result.results,
            "notifications": [event.to_dict() for event in notifications],
            "audit": scoped.audit(limit=10)["timeline"],
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
