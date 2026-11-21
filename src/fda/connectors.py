"""User-owned connectors.

A connector is a capability the customer grants to the agent. The agent sees a
name, a set of scopes and a set of actions. It never sees a credential, endpoint
or raw payload. Real work is bound operator-side: either a callable (Python
embedding) or an HMAC-signed webhook into the product's own stack (any language).
"""
import hashlib
import hmac
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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


MAX_HANDLER_RESPONSE = 64 * 1024


class WebhookHandler:
    """Operator-side adapter that calls a product endpoint for one action.

    This is the language-agnostic bridge: FDA sends only the capability context
    and the product answers with a small JSON object. The secret is read from
    the operator's environment, never from an agent bundle.
    """

    def __init__(self, url: str, secret: str = "", timeout: float = 5.0,
                 headers: Optional[dict] = None):
        if not url:
            raise ConnectorError("handler url is required")
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.headers = dict(headers or {})

    def __call__(self, ctx: dict) -> dict:
        body = json.dumps({
            "connector": ctx.get("connector", ""),
            "action": ctx.get("action", ""),
            "scopes": list(ctx.get("scopes") or []),
            "needs": list(ctx.get("needs") or []),
        }, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json"}
        if self.secret:
            signature = hmac.new(self.secret.encode("utf-8"), body,
                                 hashlib.sha256).hexdigest()
            headers["X-FDA-Signature"] = "sha256=" + signature
        headers.update(self.headers)
        request = urllib.request.Request(self.url, data=body, headers=headers,
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_HANDLER_RESPONSE + 1)
        except Exception as exc:  # never leak the url or a traceback to the agent
            raise ConnectorError("handler failed: %s" % type(exc).__name__) from exc
        if len(raw) > MAX_HANDLER_RESPONSE:
            raise ConnectorError("handler response too large")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError) as exc:
            raise ConnectorError("handler returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ConnectorError("handler must return a JSON object")
        return payload


def webhook_handler(url: str, secret: str = "", timeout: float = 5.0,
                    headers: Optional[dict] = None) -> WebhookHandler:
    """Build an adapter for ``client.register_handler``."""
    return WebhookHandler(url, secret, timeout, headers)


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
        self._handlers = {}
        for descriptor in descriptors or []:
            self.register(Connector(**descriptor))

    def register(self, connector: Connector) -> None:
        self._connectors[connector.id] = connector

    def register_handler(self, action: str, handler) -> None:
        """Wire a real adapter for one granted action (operator-side only).

        Bundles are declarative and cannot register Python. The operator binds
        an action to a callable that receives a context dict and returns a small
        typed result dict.
        """
        self._handlers[action] = handler

    def bind_webhook(self, action: str, url: str, secret: str = "",
                     timeout: float = 5.0, headers: Optional[dict] = None) -> None:
        """Bind an action to an HTTP endpoint implemented in any language."""
        self._handlers[action] = WebhookHandler(url, secret, timeout, headers)

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
        if key in self._handlers:
            result = dict(self._handlers[key]({
                "connector": connector_id,
                "action": key,
                "scopes": sorted(required),
                "needs": sorted(set(needs or [])),
            }))
            result["mode"] = "adapter"
        else:
            # Namespaced bundle actions map back to the built-in demo result.
            base_key = key.split("::", 1)[1] if "::" in key else key
            payload = SIMULATED_RESULTS.get(key, SIMULATED_RESULTS.get(base_key))
            result = dict(payload) if payload else {"ok": True}
            result["mode"] = "simulated"
        result["call_id"] = new_id("c", 10)
        result["action"] = key
        result["needs"] = sorted(set(needs or []))
        return result
