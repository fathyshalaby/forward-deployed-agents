"""Public embedding API for products that integrate forward-deployed agents.

The MCP server is one adapter around this layer; your product can use the same
runtime directly. The SDK is synchronous and standard-library only.

    from fda.sdk import Client

    client = Client.create(tenant="acme", actor="app")
    client.on("approval.requested", push_to_your_ui)

    plan = client.plan("release_watch")
    # your UI grants plan["steps"][...]["approval_id"]
    result = client.run("release_watch", approvals={"notify": approval_id})

Nothing here assumes an AI client: the product decides when to plan and run.
"""
import hashlib
import hmac
import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .bundle import bundle_skill_text, default_store, export_skill, install_bundle
from .connectors import Connector
from .runtime import Runtime, load_agents_runtime, load_runtime
from .store import StateStore
from .tools import TOOL_VERSION
from .util import new_id, utc_now

__all__ = [
    "Client", "Config", "Event", "EventBus", "RunResult", "WebhookSink",
]


# --------------------------------------------------------------------- events
@dataclass
class Event:
    name: str
    payload: dict
    ts: str = field(default_factory=utc_now)
    tenant: str = ""
    actor: str = ""
    id: str = field(default_factory=lambda: new_id("e", 10))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "ts": self.ts,
            "tenant": self.tenant, "actor": self.actor, "payload": self.payload,
        }


class EventBus:
    """In-process pub/sub with a bounded history.

    Subscribers are isolated: one failing callback never breaks a run. Use
    ``WebhookSink`` to forward events to another service.
    """

    def __init__(self, history_limit: int = 200):
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}
        self._history: List[Event] = []
        self.errors: List[dict] = []
        self.history_limit = history_limit

    def subscribe(self, event: str, callback: Callable[[Event], None]) -> Callable:
        self._subscribers.setdefault(event, []).append(callback)
        return lambda: self.unsubscribe(event, callback)

    def unsubscribe(self, event: str, callback: Callable[[Event], None]) -> None:
        if event in self._subscribers and callback in self._subscribers[event]:
            self._subscribers[event].remove(callback)

    def emit(self, name: str, payload: dict, tenant: str = "", actor: str = "") -> Event:
        event = Event(name=name, payload=payload, tenant=tenant, actor=actor)
        self._history.append(event)
        if len(self._history) > self.history_limit:
            self._history.pop(0)
        for callback in list(self._subscribers.get(name, [])) + list(
                self._subscribers.get("*", [])):
            try:
                callback(event)
            except Exception as exc:  # a subscriber must never break the engine
                self.errors.append({
                    "ts": utc_now(), "event": name,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                })
        return event

    def history(self, limit: int = 50, name: str = "") -> List[dict]:
        rows = [row for row in self._history if not name or row.name == name]
        return [row.to_dict() for row in rows[-limit:]]


class WebhookSink:
    """Forward selected events to an HTTP endpoint with an HMAC signature.

    The receiver should verify ``X-FDA-Signature`` as
    ``sha256=<hex(hmac_sha256(secret, raw_body))>`` and reject unknown senders.
    """

    def __init__(self, url: str, secret: str = "", events: Optional[List[str]] = None,
                 timeout: float = 3.0, bus: Optional[EventBus] = None):
        self.url = url
        self.secret = secret
        self.events = events or ["*"]
        self.timeout = timeout
        self.delivered = 0
        self.errors: List[dict] = []
        if bus:
            self.attach(bus)

    def attach(self, bus: EventBus) -> "WebhookSink":
        for name in self.events:
            bus.subscribe(name, self.send)
        return self

    def send(self, event: Event) -> None:
        body = json.dumps(event.to_dict(), sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.secret:
            signature = hmac.new(self.secret.encode("utf-8"), body,
                                 hashlib.sha256).hexdigest()
            headers["X-FDA-Signature"] = "sha256=" + signature
        request = urllib.request.Request(self.url, data=body, headers=headers,
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout):
                self.delivered += 1
        except Exception as exc:
            self.errors.append({
                "ts": utc_now(), "event": event.name,
                "error": "%s: %s" % (type(exc).__name__, exc),
            })


# ---------------------------------------------------------------------- result
@dataclass
class RunResult:
    run_id: str
    play_id: str
    status: str
    results: list
    tenant: str = ""
    actor: str = ""
    denied_step: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "complete"

    @classmethod
    def from_dict(cls, payload: dict) -> "RunResult":
        return cls(
            run_id=payload.get("run_id", ""), play_id=payload.get("play", ""),
            status=payload.get("status", ""), results=payload.get("results", []),
            tenant=payload.get("tenant", ""), actor=payload.get("actor", ""),
            denied_step=payload.get("denied_step", ""), raw=payload,
        )

    def to_dict(self) -> dict:
        return dict(self.raw)


# ---------------------------------------------------------------------- config
@dataclass
class Config:
    """Everything a product normally wants to override."""

    state_path: Optional[str] = None
    store: Optional[str] = None
    audit_path: Optional[str] = None
    persist_audit: bool = True
    approval_mode: Optional[str] = None
    tenant: str = ""
    actor: str = ""
    include_examples: bool = False
    playbooks_path: Optional[str] = None
    connectors_path: Optional[str] = None
    verify: bool = False
    registry_check: bool = False
    pin: bool = False
    trust: Optional[str] = None
    registry: Optional[str] = None
    webhooks: List[WebhookSink] = field(default_factory=list)

    def runtime(self) -> Runtime:
        if self.playbooks_path or self.connectors_path:
            return load_runtime(
                connectors_path=self.connectors_path,
                playbooks_path=self.playbooks_path,
                audit_path=self.audit_path,
                persist_audit=self.persist_audit,
                state_path=self.state_path,
                approval_mode=self.approval_mode,
                tenant=self.tenant,
                actor=self.actor,
            )
        return load_agents_runtime(
            store=self.store,
            include_examples=self.include_examples,
            audit_path=self.audit_path,
            persist_audit=self.persist_audit,
            state_path=self.state_path,
            approval_mode=self.approval_mode,
            tenant=self.tenant,
            actor=self.actor,
        )


# ---------------------------------------------------------------------- client
class Client:
    """Stable embedding facade over a runtime.

    Use ``Client.create`` for installed bundles, ``Client.from_paths`` for your
    own playbooks/connectors, or ``Client(runtime=...)`` when you already build
    the runtime yourself.
    """

    def __init__(self, runtime: Runtime, tenant: str = "", actor: str = "",
                 bus: Optional[EventBus] = None, config: Optional[Config] = None):
        self.runtime = runtime
        self.tenant = tenant or runtime.tenant
        self.actor = actor or runtime.actor
        self.events = bus or EventBus()
        self.config = config or Config()
        self._scoped = False

    @classmethod
    def create(cls, config: Optional[Config] = None, **kwargs) -> "Client":
        config = config or Config(**kwargs)
        runtime = config.runtime()
        client = cls(runtime, tenant=config.tenant, actor=config.actor,
                     config=config)
        for sink in config.webhooks:
            sink.attach(client.events)
        return client

    @classmethod
    def from_paths(cls, playbooks_path, connectors_path=None, **kwargs) -> "Client":
        config = Config(playbooks_path=str(playbooks_path),
                        connectors_path=(str(connectors_path) if connectors_path else None),
                        **kwargs)
        return cls.create(config)

    def as_tenant(self, tenant: str, actor: str = "") -> "Client":
        """Return a lightweight view whose calls carry this tenant/actor."""
        scoped = Client(self.runtime, tenant=tenant, actor=actor or self.actor,
                        bus=self.events, config=self.config)
        scoped._scoped = True
        return scoped

    def _context(self, context: Optional[dict] = None) -> dict:
        merged = dict(context or {})
        if self.tenant:
            merged.setdefault("tenant", self.tenant)
        if self.actor:
            merged.setdefault("actor", self.actor)
        return merged

    def _emit(self, name: str, payload: dict) -> None:
        self.events.emit(name, payload, tenant=self.tenant, actor=self.actor)

    # ------------------------------------------------------------- discovery
    def list_agents(self) -> dict:
        return {"agents": list(self.runtime.bundles),
                "count": len(self.runtime.bundles),
                "tool_version": TOOL_VERSION}

    def describe_agent(self, agent_id: str) -> dict:
        for row in self.runtime.bundles:
            if row["id"] == agent_id:
                return {key: value for key, value in row.items() if key != "source"}
        raise KeyError("unknown agent: %s" % agent_id)

    def agent_skill(self, agent_id: str, prefer_custom: bool = True) -> str:
        for row in self.runtime.bundles:
            if row["id"] == agent_id:
                from .bundle import load_bundle_dir
                bundle = load_bundle_dir(row["source"])
                return bundle_skill_text(bundle, prefer_custom=prefer_custom)
        raise KeyError("unknown agent: %s" % agent_id)

    def export_skill(self, agent_id: str, output, prefer_custom: bool = True) -> str:
        for row in self.runtime.bundles:
            if row["id"] == agent_id:
                from .bundle import load_bundle_dir
                bundle = load_bundle_dir(row["source"])
                return str(export_skill(bundle, output,
                                        prefer_custom=prefer_custom))
        raise KeyError("unknown agent: %s" % agent_id)

    def list_plays(self) -> dict:
        return {"plays": self.runtime.engine.list()}

    def describe_play(self, play_id: str) -> dict:
        return self.runtime.engine.describe(play_id)

    # ------------------------------------------------------------------ runs
    def plan(self, play_id: str, context: Optional[dict] = None) -> dict:
        payload = self.runtime.engine.plan(play_id, self._context(context))
        approval_ids = [step["approval_id"] for step in payload["steps"]
                        if step.get("approval_id")]
        if approval_ids:
            self._emit("approval.requested", {
                "play_id": play_id, "approval_ids": approval_ids,
                "tenant": payload.get("tenant", self.tenant),
                "actor": payload.get("actor", self.actor),
            })
        self._emit("play.planned", {"play_id": play_id,
                                    "steps": len(payload["steps"])})
        return payload

    def run(self, play_id: str, approvals: Optional[dict] = None,
            context: Optional[dict] = None) -> RunResult:
        self._emit("run.started", {"play_id": play_id,
                                   "steps": len(approvals or {})})
        payload = self.runtime.engine.run(play_id, approvals, self._context(context))
        result = RunResult.from_dict(payload)
        self._emit("run.finished", result.to_dict())
        if not result.ok:
            self._emit("run.denied", {"play_id": play_id,
                                      "step": result.denied_step,
                                      "reason": result.results[-1].get("error", "")
                                      if result.results else ""})
        return result

    def status(self, run_id: str) -> RunResult:
        return RunResult.from_dict(self.runtime.engine.status(run_id))

    def privacy_check(self, tool: str, needs: List[str], purpose: str,
                      connector_id: str, approval_id: str = "",
                      write: bool = False, context: Optional[dict] = None) -> dict:
        ctx = self._context(context)
        return self.runtime.privacy.check(
            tool=tool, needs=needs, purpose=purpose, connector_id=connector_id,
            approval_id=approval_id, write=write, actor=ctx.get("actor", ""),
        )

    # ------------------------------------------------------------- approvals
    def pending_approvals(self, limit: int = 50) -> dict:
        state = self.runtime.state
        rows = state.approval_list("pending", limit) if state else []
        return {"approvals": rows, "count": len(rows)}

    def approval_status(self, approval_id: str) -> dict:
        return self.runtime.approvals.status(approval_id)

    def request_approval(self, action: str, needs: List[str], purpose: str,
                         reason: str = "", ttl_seconds: int = 0,
                         context: Optional[dict] = None) -> dict:
        ctx = self._context(context)
        payload = self.runtime.approvals.request(
            action=action, reason=reason or purpose, needs=needs, purpose=purpose,
            actor=ctx.get("actor", ""), ttl_seconds=ttl_seconds,
        )
        self._emit("approval.requested", {
            "approval_ids": [payload["approval_id"]], "action": action,
            "purpose": purpose, "tenant": ctx.get("tenant", ""),
            "actor": ctx.get("actor", ""),
        })
        return payload

    def grant_approval(self, approval_id: str, approver: str) -> dict:
        """Privileged out-of-band decision, even in external approval mode."""
        state = self.runtime.state
        if not state:
            return self.runtime.approvals.grant(approval_id, approver)
        ok, status = state.approval_decide(approval_id, "grant", approver)
        if not ok:
            raise ValueError(status)
        self._emit("approval.granted", {"approval_id": approval_id,
                                        "approver": approver})
        return {"approval_id": approval_id, "status": status, "approver": approver}

    def deny_approval(self, approval_id: str, approver: str) -> dict:
        state = self.runtime.state
        if not state:
            return self.runtime.approvals.deny(approval_id, approver)
        ok, status = state.approval_decide(approval_id, "deny", approver)
        if not ok:
            raise ValueError(status)
        self._emit("approval.denied", {"approval_id": approval_id,
                                       "approver": approver})
        return {"approval_id": approval_id, "status": status, "approver": approver}

    # ------------------------------------------------------------ connectors
    def register_connector(self, identifier: str, name: str, scopes: List[str],
                           actions: List[str], handler: Optional[Callable] = None,
                           approval_required: Optional[List[str]] = None,
                           description: str = "") -> dict:
        """Declare a capability and optionally bind its real adapter."""
        connector = Connector(
            id=identifier, name=name, scopes=list(scopes), actions=list(actions),
            approval_required=list(approval_required or []), description=description,
        )
        self.runtime.connectors.register(connector)
        for action in actions:
            key = action if action.startswith(identifier + ".") else (
                identifier + "." + action)
            if handler:
                self.runtime.connectors.register_handler(key, handler)
        return connector.public()

    def register_handler(self, action: str, handler: Callable) -> None:
        """Bind an operator-side callable to one granted action."""
        self.runtime.connectors.register_handler(action, handler)

    def list_connectors(self) -> dict:
        return {"connectors": self.runtime.connectors.list_public()}

    # ------------------------------------------------------------------- ops
    def audit(self, limit: int = 30) -> dict:
        return self.runtime.audit.explain(limit)

    def verify_audit(self) -> dict:
        state = self.runtime.state
        return state.audit_verify() if state else {"entries": 0, "ok": True}

    def ops_status(self) -> dict:
        state = self.runtime.state
        return {
            "approval_mode": self.runtime.approval_mode,
            "tenant": self.tenant, "actor": self.actor,
            "state_path": str(state.path) if state else "",
            "kill_switch": state.kill_check(self.tenant) if state else {
                "paused": False},
            "stats": state.stats() if state else {},
            "audit_chain": self.verify_audit(),
            "events": len(self.events.history(limit=1000)),
        }

    def pause(self, scope: str = "*", reason: str = "") -> dict:
        if not self.runtime.state:
            raise RuntimeError("durable state is required for the kill switch")
        self.runtime.state.kill_set(scope, True, reason)
        self._emit("ops.paused", {"scope": scope, "reason": reason})
        return {"scope": scope, "paused": True}

    def resume(self, scope: str = "*") -> dict:
        if not self.runtime.state:
            raise RuntimeError("durable state is required for the kill switch")
        self.runtime.state.kill_set(scope, False, "")
        self._emit("ops.resumed", {"scope": scope})
        return {"scope": scope, "paused": False}

    def revoke_agent(self, agent_id: str, version: str = "*", reason: str = "") -> dict:
        if not self.runtime.state:
            raise RuntimeError("durable state is required for revocation")
        self.runtime.state.revoke(agent_id, version, reason)
        self._emit("agent.revoked", {"agent_id": agent_id,
                                     "version": version, "reason": reason})
        return {"agent_id": agent_id, "version": version, "revoked": True}

    def install_agent(self, archive, force: bool = False, verify: bool = False,
                      registry_check: bool = False, pin: bool = False) -> dict:
        """Install a bundle programmatically; restarts pick it up."""
        from .security import Keyring, Registry, Verifier

        kwargs = {
            "store": self.config.store or default_store(),
            "force": force,
            "state": self.runtime.state,
            "pin": pin,
        }
        if verify or self.config.verify:
            kwargs["verifier"] = Verifier(Keyring(self.config.trust), require=True)
        if registry_check or self.config.registry_check:
            kwargs["registry"] = Registry(self.config.registry)
        bundle = install_bundle(archive, **kwargs)
        self._emit("agent.installed", {"agent_id": bundle.manifest.id,
                                       "version": bundle.manifest.version})
        return bundle.public()

    def on(self, event: str, callback: Callable[[Event], None]) -> Callable:
        return self.events.subscribe(event, callback)
