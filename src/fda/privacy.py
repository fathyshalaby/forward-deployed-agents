"""Data minimisation, approvals and audit for the forward-deployed agent.

The rule mirrors the Enron case: use the smallest data class that can answer the
question. Aggregates and metadata are allowed by default. Identifiers and free
text need a stated purpose and a granted, single-use approval.
"""
import json
import time
from dataclasses import dataclass, field
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
    actor: str = ""
    playbook_hash: str = ""
    args_hash: str = ""
    expires_at: float = 0.0


class ApprovalStore:
    """Human-gated, single-use approvals.

    ``state`` is an optional durable SQLite store. When present, decisions are
    atomic and survive restarts; the external approval UI writes to the same
    store. In demo mode the in-memory path is unchanged.
    """

    def __init__(self, state=None, mode: str = "demo"):
        self.state = state
        self.mode = mode
        self._approvals: Dict[str, Approval] = {}

    def request(self, action: str, reason: str, needs, purpose: str,
                actor: str = "", playbook_hash: str = "",
                args_hash: str = "", ttl_seconds: int = 0) -> dict:
        approval = Approval(
            id=new_id("a"),
            action=action,
            reason=reason,
            needs=sorted(set(needs)),
            purpose=purpose,
            actor=actor,
            playbook_hash=playbook_hash,
            args_hash=args_hash,
            expires_at=time.time() + ttl_seconds if ttl_seconds else 0.0,
        )
        self._approvals[approval.id] = approval
        if self.state:
            self.state.approval_save({
                "id": approval.id, "action": approval.action,
                "reason": approval.reason, "needs": approval.needs,
                "purpose": approval.purpose, "actor": actor,
                "playbook_hash": playbook_hash, "args_hash": args_hash,
                "status": "pending", "granted_by": "", "used": False,
                "expires_at": approval.expires_at, "created_at": utc_now(),
            })
        return {
            "approval_id": approval.id,
            "action": action,
            "reason": reason,
            "needs": approval.needs,
            "purpose": purpose,
            "actor": actor,
            "playbook_hash": playbook_hash,
            "args_hash": args_hash,
            "status": "pending",
            "expires_at": approval.expires_at,
        }

    def grant(self, approval_id: str, approver: str, mode: str = None) -> dict:
        """Grant an approval. External mode forbids grants from the agent side."""
        mode = self.mode if mode is None else mode
        if mode == "external":
            raise PrivacyError(
                "approval must be granted out-of-band via `fda approvals grant` "
                "or the approval UI"
            )
        if self.state:
            ok, status = self.state.approval_decide(approval_id, "grant", approver)
            if not ok:
                raise PrivacyError(status)
            approval = self._get(approval_id)
            approval.granted = True
            approval.approver = approver
            return {"approval_id": approval_id, "status": status,
                    "approver": approver}
        approval = self._get(approval_id)
        if approval.granted:
            raise PrivacyError("approval already granted")
        if approval.expires_at and time.time() > approval.expires_at:
            raise PrivacyError("approval expired")
        approval.granted = True
        approval.approver = approver
        return {"approval_id": approval.id, "status": "granted", "approver": approver}

    def status(self, approval_id: str) -> dict:
        """Public read of one approval, for the approval UI and MCP clients."""
        approval = self._get(approval_id)
        return {
            "approval_id": approval.id,
            "action": approval.action,
            "reason": approval.reason,
            "needs": approval.needs,
            "purpose": approval.purpose,
            "actor": approval.actor,
            "playbook_hash": approval.playbook_hash,
            "args_hash": approval.args_hash,
            "granted": approval.granted,
            "used": approval.used,
            "approver": approval.approver,
            "expires_at": approval.expires_at,
        }

    def deny(self, approval_id: str, approver: str) -> dict:
        if self.state:
            ok, status = self.state.approval_decide(approval_id, "deny", approver)
            if not ok:
                raise PrivacyError(status)
            return {"approval_id": approval_id, "status": status,
                    "approver": approver}
        approval = self._get(approval_id)
        if approval.granted:
            raise PrivacyError("approval already granted")
        approval.granted = False
        approval.approver = approver
        return {"approval_id": approval_id, "status": "denied",
                "approver": approver}

    def _get(self, approval_id: str) -> Approval:
        if self.state:
            row = self.state.approval_get(approval_id)
            if row is None:
                raise PrivacyError("unknown approval id")
            return Approval(
                id=row["id"], action=row["action"], reason=row["reason"],
                needs=json.loads(row["needs"]),
                purpose=row["purpose"], granted=row["status"] == "granted",
                approver=row["granted_by"], used=bool(row["used"]),
                actor=row["actor"], playbook_hash=row["playbook_hash"],
                args_hash=row["args_hash"], expires_at=row["expires_at"],
            )
        if approval_id not in self._approvals:
            raise PrivacyError("unknown approval id")
        return self._approvals[approval_id]

    def consume(self, approval_id: str, action: str, needs, purpose: str,
                actor: str = "", playbook_hash: str = "",
                args_hash: str = "") -> Approval:
        if self.state:
            row, reason = self.state.approval_consume(
                approval_id, action, needs, purpose,
                actor=actor or None, playbook_hash=playbook_hash or None,
                args_hash=args_hash or None,
            )
            if reason:
                raise PrivacyError(reason)
            return Approval(
                id=row["id"], action=row["action"], reason=row["reason"],
                needs=json.loads(row["needs"]),
                purpose=row["purpose"], granted=True, approver=row["granted_by"],
                used=True, actor=row["actor"],
                playbook_hash=row["playbook_hash"], args_hash=row["args_hash"],
            )
        approval = self._get(approval_id)
        if not approval.granted:
            raise PrivacyError("approval not granted")
        if approval.used:
            raise PrivacyError("approval already used")
        if approval.expires_at and time.time() > approval.expires_at:
            raise PrivacyError("approval expired")
        if approval.action != action:
            raise PrivacyError("approval is for a different action")
        if approval.purpose != purpose:
            raise PrivacyError("approval purpose does not match")
        if not set(needs).issubset(set(approval.needs)):
            raise PrivacyError("approval does not cover all requested data classes")
        for field_name, expected in (("actor", actor),
                                     ("playbook_hash", playbook_hash),
                                     ("args_hash", args_hash)):
            bound = getattr(approval, field_name)
            if bound and expected and bound != expected:
                raise PrivacyError("approval %s does not match" % field_name)
        approval.used = True
        return approval


class PrivacyGate:
    """Decides whether a planned connector call is allowed."""

    def __init__(self, approvals: ApprovalStore, connectors):
        self.approvals = approvals
        self.connectors = connectors

    def check(self, tool: str, needs, purpose: str, connector_id: str,
              approval_id: Optional[str] = None, write: bool = False,
              actor: str = "", playbook_hash: str = "",
              args_hash: str = "") -> dict:
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
                approval = self.approvals.consume(
                    approval_id, tool, needs, purpose, actor=actor,
                    playbook_hash=playbook_hash, args_hash=args_hash,
                )
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

    def __init__(self, path=None, state=None, tenant: str = "", actor: str = ""):
        self.path = Path(path) if path else None
        self.state = state
        self.tenant = tenant
        self.actor = actor
        self.entries: List[dict] = []

    def set_context(self, tenant: str = "", actor: str = "") -> None:
        self.tenant, self.actor = tenant, actor

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
        if self.state:
            self.state.audit_append(clean, tenant=self.tenant, actor=self.actor)
        return clean

    def explain(self, limit: int = 30) -> dict:
        if self.state:
            payload = self.state.audit_list(limit)
            payload["note"] = (
                "Durable hash-chained audit. Tenant and actor are recorded on "
                "every entry. Free text appears only as a hash."
            )
            return payload
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
