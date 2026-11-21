"""Wiring: customer-supplied connectors and playbooks into one runtime.

Everything is replaceable. Point FDA_CONNECTORS and FDA_PLAYBOOKS at your own
JSON files for a single-agent server, or install agent bundles with
``python3 -m fda agents install`` and run the multi-agent server with
``python3 -m fda serve``.

In deployment mode the runtime uses a SQLite state store for runs, approvals,
the hash-chained audit trail, revocations, pins and the kill switch. Set
``FDA_APPROVAL_MODE=external`` so the model cannot grant its own approvals.
Set ``FDA_HANDLERS`` to a JSON file mapping actions to signed product webhooks;
that is the language-agnostic bridge to real connectors.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .bundle import BundleError, default_store, list_installed, load_bundle_dir
from .connectors import ConnectorRegistry
from .plays import PlayEngine, load_playbooks
from .privacy import ApprovalStore, AuditLog, PrivacyGate
from .store import StateStore

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS = REPO_ROOT / "examples" / "connectors.json"
DEFAULT_PLAYBOOKS = REPO_ROOT / "examples" / "playbooks"
DEFAULT_AUDIT = REPO_ROOT / "data" / "runtime" / "audit.jsonl"


def examples_present() -> bool:
    """True in a source checkout, false in an installed wheel."""
    return DEFAULT_CONNECTORS.is_file() and DEFAULT_PLAYBOOKS.is_dir()


def default_state_path() -> Path:
    return Path(os.environ.get("FDA_STATE") or
                (Path.home() / ".fda" / "state.db"))


def default_audit_path() -> Path:
    if examples_present():
        return DEFAULT_AUDIT
    return Path.home() / ".fda" / "audit.jsonl"


def default_approval_mode() -> str:
    return os.environ.get("FDA_APPROVAL_MODE", "demo").lower()


@dataclass
class Runtime:
    connectors: ConnectorRegistry
    playbooks: object
    approvals: ApprovalStore
    privacy: PrivacyGate
    audit: AuditLog
    engine: PlayEngine
    bundles: tuple = field(default_factory=tuple)
    state: object = None
    approval_mode: str = "demo"
    tenant: str = ""
    actor: str = ""


def _bind_webhooks(connectors) -> None:
    """Bind operator-side HTTP handlers from ``FDA_HANDLERS``.

    The file maps a namespaced action to a product endpoint. Secrets are read
    from the environment named by ``secret_env``; nothing enters a bundle.
    """
    config_path = os.environ.get("FDA_HANDLERS", "")
    if not config_path:
        return
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read FDA_HANDLERS config") from exc
    if not isinstance(payload, dict):
        raise ValueError("FDA_HANDLERS must map actions to handler configs")
    for action, spec in payload.items():
        if not isinstance(spec, dict) or not spec.get("url"):
            raise ValueError("invalid FDA_HANDLERS entry: %s" % action)
        secret_name = spec.get("secret_env", "")
        secret = (os.environ.get(secret_name, "") if secret_name
                  else spec.get("secret", ""))
        connectors.bind_webhook(
            action, str(spec["url"]), secret,
            float(spec.get("timeout", 5.0)), spec.get("headers") or {},
        )


def _build(playbooks, descriptors, audit_path, persist_audit, bundles=(),
           state=None, approval_mode="demo", tenant="", actor=""):
    connectors = ConnectorRegistry(descriptors)
    _bind_webhooks(connectors)
    approvals = ApprovalStore(state, mode=approval_mode)
    audit = AuditLog(audit_path if persist_audit else None, state=state,
                     tenant=tenant, actor=actor)
    privacy = PrivacyGate(approvals, connectors)
    engine = PlayEngine(playbooks, connectors, privacy, audit, state=state,
                        default_tenant=tenant, default_actor=actor)
    return Runtime(connectors, playbooks, approvals, privacy, audit, engine,
                   tuple(bundles), state, approval_mode, tenant, actor)


def load_runtime(connectors_path=None, playbooks_path=None, audit_path=None,
                 persist_audit=True, state_path=None, approval_mode=None,
                 tenant="", actor="") -> Runtime:
    """Single-agent runtime (backwards compatible: examples + env overrides)."""
    env_connectors = os.environ.get("FDA_CONNECTORS")
    env_playbooks = os.environ.get("FDA_PLAYBOOKS")
    want_connectors = bool(connectors_path or env_connectors) or examples_present()
    want_playbooks = bool(playbooks_path or env_playbooks) or examples_present()
    connectors_path = Path(connectors_path or env_connectors or DEFAULT_CONNECTORS)
    playbooks_path = Path(playbooks_path or env_playbooks or DEFAULT_PLAYBOOKS)
    if persist_audit and audit_path is None:
        audit_path = os.environ.get("FDA_AUDIT", default_audit_path())
    descriptors = (json.loads(connectors_path.read_text(encoding="utf-8"))
                   if want_connectors else [])
    playbooks = load_playbooks(playbooks_path) if want_playbooks else {}
    state = (StateStore(state_path or default_state_path())
             if persist_audit else None)
    return _build(playbooks, descriptors, audit_path, persist_audit, state=state,
                  approval_mode=approval_mode or default_approval_mode(),
                  tenant=tenant or os.environ.get("FDA_TENANT", ""),
                  actor=actor or os.environ.get("FDA_ACTOR", ""))


def load_agents_runtime(store=None, include_examples=True, audit_path=None,
                        persist_audit=True, state_path=None, approval_mode=None,
                        tenant="", actor="") -> Runtime:
    """Multi-agent runtime: example plays plus every installed agent bundle.

    Revoked bundles are skipped. Pinned bundles whose content changed fail
    closed. Ids are namespaced with ``<bundle id>::`` on load.
    """
    store = Path(store) if store else default_store()
    if persist_audit and audit_path is None:
        audit_path = os.environ.get("FDA_AUDIT", default_audit_path())
    state = (StateStore(state_path or default_state_path())
             if persist_audit else None)

    descriptors = []
    playbooks = {}
    bundles = []
    if (include_examples and examples_present()
            and os.environ.get("FDA_NO_EXAMPLES", "") not in ("1", "true")):
        descriptors = json.loads(DEFAULT_CONNECTORS.read_text(encoding="utf-8"))
        playbooks = dict(load_playbooks(DEFAULT_PLAYBOOKS))

    for installed in list_installed(store):
        if installed.get("status") == "invalid":
            continue
        identifier = installed["id"]
        if state and state.is_revoked(identifier, installed.get("version", "")):
            continue
        expected_hash = ""
        if state:
            pin = state.pin_get(identifier)
            if pin:
                expected_hash = pin["content_hash"]
        try:
            bundle = load_bundle_dir(store / identifier,
                                     expected_hash=expected_hash)
        except BundleError as exc:
            # A pinned bundle that changed is a hard failure, not a skip.
            raise ValueError("cannot load installed agent %s: %s"
                             % (identifier, exc))
        for play_id, play in bundle.playbooks.items():
            if play_id in playbooks:
                raise ValueError("duplicate playbook id: %s" % play_id)
            playbooks[play_id] = play
        descriptors.extend(bundle.connectors)
        bundles.append(bundle.public())

    return _build(
        playbooks, descriptors, audit_path, persist_audit, bundles,
        state=state,
        approval_mode=approval_mode or default_approval_mode(),
        tenant=tenant or os.environ.get("FDA_TENANT", ""),
        actor=actor or os.environ.get("FDA_ACTOR", ""),
    )
