"""User-owned connectors.

A connector is a capability the customer grants to the agent. The agent sees a
name, a set of scopes and a set of actions. It never sees a credential, endpoint
or raw payload. This prototype simulates execution; a real deployment swaps the
simulated result table for calls made inside the customer boundary.
"""
from dataclasses import dataclass, field
from typing import Dict, List

from .util import new_id


class ConnectorError(Exception):
    """Raised when a connector, action or scope is unavailable."""


def _action_key(connector_id: str, action: str) -> str:
    """Accept either 'create' or 'tickets.create' in playbooks."""
    prefix = connector_id + "."
    return action if action.startswith(prefix) else prefix + action


# Simulated, non-sensitive results. No free text from the user is echoed back.
SIMULATED_RESULTS = {
    "identity.get_user": {"found": True, "status": "active"},
    "identity.list_groups": {"group_count": 4},
    "identity.reset_mfa": {"mfa_reset": True},
    "tickets.search": {"match_count": 3},
    "tickets.create": {"created": True},
    "tickets.comment": {"comment_added": True},
    "tickets.resolve": {"resolved": True},
    "chat.search": {"match_count": 2},
    "chat.post_update": {"posted": True},
    "repo.open_issue": {"issue_opened": True},
    "repo.create_pull_request": {"pull_request_opened": True},
    "observability.get_metrics": {"error_rate": 0.04, "p95_ms": 380},
    "observability.get_incident_summary": {"incident_count": 1, "severity": "high"},
    "directory.find_team": {"team": "platform", "member_count": 6},
    "directory.get_owner": {"owner_role": "support-lead"},
}


@dataclass
class Connector:
    id: str
    name: str
    scopes: List[str]
    actions: List[str]
    description: str = ""
    approval_required: List[str] = field(default_factory=list)

    def public(self) -> dict:
        """The only representation exposed to the agent and to published logs."""
        return {
            "id": self.id,
            "name": self.name,
            "scopes": sorted(self.scopes),
            "actions": sorted(self.actions),
            "approval_required": sorted(self.approval_required),
            "description": self.description,
        }


class ConnectorRegistry:
    """Holds the capabilities the user chose to expose."""

    def __init__(self, descriptors=None):
        self._connectors: Dict[str, Connector] = {}
        for descriptor in descriptors or []:
            self.register(Connector(**descriptor))

    def register(self, connector: Connector) -> None:
        self._connectors[connector.id] = connector

    def list_public(self) -> List[dict]:
        return [self._connectors[key].public() for key in sorted(self._connectors)]

    def get(self, connector_id: str) -> Connector:
        if connector_id not in self._connectors:
            raise ConnectorError("connector not granted: %s" % connector_id)
        return self._connectors[connector_id]

    def has_action(self, connector_id: str, action: str) -> bool:
        return _action_key(connector_id, action) in self.get(connector_id).actions

    def call(self, connector_id: str, action: str, scopes=None, needs=None):
        """Execute a simulated action through a granted connector.

        `payload` is deliberately absent: the agent passes only scopes and data
        classes, so user content cannot be echoed into outputs or the audit log.
        """
        connector = self.get(connector_id)
        key = _action_key(connector_id, action)
        if key not in connector.actions:
            raise ConnectorError("action not granted: %s" % key)
        required = set(scopes or [])
        if not required.issubset(set(connector.scopes)):
            missing = sorted(required - set(connector.scopes))
            raise ConnectorError("scope not granted: %s" % ", ".join(missing))
        if key not in SIMULATED_RESULTS:
            raise ConnectorError("no simulated handler for %s" % key)
        result = dict(SIMULATED_RESULTS[key])
        result["call_id"] = new_id("c", 10)
        result["action"] = key
        result["needs"] = sorted(set(needs or []))
        return result
