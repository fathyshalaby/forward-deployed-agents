"""Data minimisation, approvals and audit for the forward-deployed agent.

The rule mirrors the Enron case: use the smallest data class that can answer the
question. Aggregates and metadata are allowed by default. Identifiers and free
text need a stated purpose and a granted, single-use approval.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .util import append_jsonl, new_id, redact, text_hash, utc_now

DEFAULT_ALLOWED = frozenset({"aggregate", "metadata"})
SENSITIVE = frozenset({"identifier", "content"})
KNOWN_NEEDS = DEFAULT_ALLOWED | SENSITIVE

# A need maps to the connector scope that must have been granted by the user.
SCOPE_FOR_NEED = {
    "aggregate": "read",
    "metadata": "read",
    "identifier": "identify",
    "content": "content",
}

_HASHED_KEYS = frozenset({"text", "raw", "payload", "complaint_text"})


class PrivacyError(Exception):
    """Raised when a planned action fails the minimisation policy."""


@dataclass
class Approval:
    id: str
    action: str
    reason: str
    needs: List[str]
    purpose: str
    granted: bool = False
    approver: str = ""
    used: bool = False


class ApprovalStore:
    """Human-gated, single-use approvals. `grant` stands in for a customer UI."""

    def __init__(self):
        self._approvals: Dict[str, Approval] = {}

    def request(self, action: str, reason: str, needs, purpose: str) -> dict:
        approval = Approval(
            id=new_id("a"),
            action=action,
            reason=reason,
            needs=sorted(set(needs)),
            purpose=purpose,
        )
        self._approvals[approval.id] = approval
        return {
            "approval_id": approval.id,
            "action": action,
            "reason": reason,
            "needs": approval.needs,
            "purpose": purpose,
            "status": "pending",
        }

    def grant(self, approval_id: str, approver: str) -> dict:
        approval = self._get(approval_id)
        if approval.granted:
            raise PrivacyError("approval already granted")
        approval.granted = True
        approval.approver = approver
        return {"approval_id": approval.id, "status": "granted", "approver": approver}

    def _get(self, approval_id: str) -> Approval:
        if approval_id not in self._approvals:
            raise PrivacyError("unknown approval id")
        return self._approvals[approval_id]

    def consume(self, approval_id: str, action: str, needs, purpose: str) -> Approval:
        approval = self._get(approval_id)
        if not approval.granted:
            raise PrivacyError("approval not granted")
        if approval.used:
            raise PrivacyError("approval already used")
        if approval.action != action:
            raise PrivacyError("approval is for a different action")
        if approval.purpose != purpose:
            raise PrivacyError("approval purpose does not match")
        if not set(needs).issubset(set(approval.needs)):
            raise PrivacyError("approval does not cover all requested data classes")
        approval.used = True
        return approval


class PrivacyGate:
    """Decides whether a planned connector call is allowed."""

    def __init__(self, approvals: ApprovalStore, connectors):
        self.approvals = approvals
        self.connectors = connectors

    def check(self, tool: str, needs, purpose: str, connector_id: str,
              approval_id: Optional[str] = None, write: bool = False) -> dict:
        needs = sorted(set(needs or []))
        unknown = sorted(set(needs) - KNOWN_NEEDS)
        if unknown:
            return self._deny(tool, "unknown data class: %s" % ", ".join(unknown))
        if "content" in needs and not purpose:
            return self._deny(tool, "content requires an explicit purpose")
        sensitive = sorted(set(needs) & SENSITIVE)
        approval = None
        if write or sensitive:
            if not approval_id:
                return self._deny(
                    tool,
                    "write actions require an approval id" if write
                    else "sensitive data requires an approval id",
                )
            try:
                approval = self.approvals.consume(approval_id, tool, needs, purpose)
            except PrivacyError as exc:
                return self._deny(tool, str(exc))
        connector = self.connectors.get(connector_id)
        missing = sorted(
            SCOPE_FOR_NEED[need] for need in needs
            if SCOPE_FOR_NEED[need] not in connector.scopes
        )
        if missing:
            return self._deny(tool, "missing connector scope: %s" % ", ".join(sorted(set(missing))))
        if write and "write" not in connector.scopes:
            return self._deny(tool, "missing connector scope: write")
        return {
            "decision": "allow",
            "tool": tool,
            "needs": needs,
            "purpose": purpose,
            "connector": connector_id,
            "write": write,
            "approval_id": approval_id or "",
            "approver": approval.approver if approval else "",
        }

    @staticmethod
    def _deny(tool: str, reason: str) -> dict:
        return {"decision": "deny", "tool": tool, "reason": redact(reason)}


class AuditLog:
    """Append-only, content-free record of what the agent did and why."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.entries: List[dict] = []

    def record(self, tool: str, decision: str, **fields) -> dict:
        clean = {"ts": utc_now(), "tool": tool, "decision": decision}
        for key, value in fields.items():
            if value is None:
                continue
            if key in _HASHED_KEYS and isinstance(value, str):
                clean[key + "_hash"] = text_hash(value)
            elif isinstance(value, str):
                clean[key] = redact(value)
            elif isinstance(value, (list, dict, int, float, bool)):
                clean[key] = value
        self.entries.append(clean)
        if self.path:
            append_jsonl(self.path, clean)
        return clean

    def explain(self, limit: int = 30) -> dict:
        entries = self.entries[-limit:]
        return {
            "entries": len(self.entries),
            "shown": len(entries),
            "timeline": [
                {
                    "ts": entry.get("ts"),
                    "tool": entry.get("tool"),
                    "decision": entry.get("decision"),
                    "connector": entry.get("connector", ""),
                    "action": entry.get("action", ""),
                    "needs": entry.get("needs", []),
                    "approval_id": entry.get("approval_id", ""),
                    "approver": entry.get("approver", ""),
                }
                for entry in entries
            ],
            "note": "Free text is stored only as a short hash. No credentials or payloads are logged.",
        }
