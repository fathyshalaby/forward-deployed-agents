"""Wiring: customer-supplied connectors and playbooks into one runtime.

Everything is replaceable. Point FDA_CONNECTORS and FDA_PLAYBOOKS at your own
JSON files; nothing in the engine assumes a particular customer or workflow.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .connectors import ConnectorRegistry
from .plays import PlayEngine, load_playbooks
from .privacy import ApprovalStore, AuditLog, PrivacyGate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS = REPO_ROOT / "examples" / "connectors.json"
DEFAULT_PLAYBOOKS = REPO_ROOT / "examples" / "playbooks"
DEFAULT_AUDIT = REPO_ROOT / "data" / "runtime" / "audit.jsonl"


@dataclass
class Runtime:
    connectors: ConnectorRegistry
    playbooks: object
    approvals: ApprovalStore
    privacy: PrivacyGate
    audit: AuditLog
    engine: PlayEngine


def load_runtime(connectors_path=None, playbooks_path=None, audit_path=None,
                 persist_audit=True) -> Runtime:
    connectors_path = Path(connectors_path or os.environ.get("FDA_CONNECTORS")
                           or DEFAULT_CONNECTORS)
    playbooks_path = Path(playbooks_path or os.environ.get("FDA_PLAYBOOKS")
                          or DEFAULT_PLAYBOOKS)
    if persist_audit and audit_path is None:
        audit_path = os.environ.get("FDA_AUDIT", DEFAULT_AUDIT)

    descriptors = json.loads(connectors_path.read_text(encoding="utf-8"))
    connectors = ConnectorRegistry(descriptors)
    approvals = ApprovalStore()
    audit = AuditLog(audit_path if persist_audit else None)
    privacy = PrivacyGate(approvals, connectors)
    playbooks = load_playbooks(playbooks_path)
    engine = PlayEngine(playbooks, connectors, privacy, audit)
    return Runtime(connectors, playbooks, approvals, privacy, audit, engine)
