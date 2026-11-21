"""General playbook engine.

A playbook is a JSON description of work a forward-deployed agent may perform.
Nothing in the engine is specific to onboarding, support or IT: bring your own
playbooks and connectors. The engine only enforces scope, data minimisation,
approval and audit.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .connectors import ConnectorError
from .privacy import PrivacyError
from .util import new_id

VALID_STEP_TOOLS = frozenset({"connectors.list", "connectors.call", "note"})


class PlayError(Exception):
    """Raised for invalid playbooks or invalid run requests."""


@dataclass
class Step:
    id: str
    title: str
    tool: str
    needs: List[str] = field(default_factory=list)
    purpose: str = ""
    connector: str = ""
    action: str = ""
    scopes: List[str] = field(default_factory=list)
    write: bool = False
    approval: bool = False

    @classmethod
    def from_dict(cls, raw: dict) -> "Step":
        step = cls(
            id=raw["id"],
            title=raw.get("title", raw["id"]),
            tool=raw.get("tool", "note"),
            needs=list(raw.get("needs", [])),
            purpose=raw.get("purpose", ""),
            connector=raw.get("connector", ""),
            action=raw.get("action", ""),
            scopes=list(raw.get("scopes", [])),
            write=bool(raw.get("write", False)),
            approval=bool(raw.get("approval", False)),
        )
        if step.tool not in VALID_STEP_TOOLS:
            raise PlayError("unknown step tool: %s" % step.tool)
        if step.approval and not step.write and not step.needs:
            # Approval on a pure read is still legal; keep it explicit.
            pass
        if step.tool == "connectors.call" and not (step.connector and step.action):
            raise PlayError("step %s needs connector and action" % step.id)
        if step.write:
            step.approval = True
        return step

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "needs": sorted(self.needs),
            "purpose": self.purpose,
            "connector": self.connector,
            "action": self.action,
            "scopes": sorted(self.scopes),
            "write": self.write,
            "approval_required": self.approval,
        }


@dataclass
class Playbook:
    id: str
    name: str
    description: str
    purpose: str
    tags: List[str]
    steps: List[Step]
    source: str = ""
    content_hash: str = ""

    @classmethod
    def from_dict(cls, raw: dict, source: str = "") -> "Playbook":
        play = cls(
            id=raw["id"],
            name=raw.get("name", raw["id"]),
            description=raw.get("description", ""),
            purpose=raw.get("purpose", ""),
            tags=list(raw.get("tags", [])),
            steps=[Step.from_dict(item) for item in raw.get("steps", [])],
            source=source,
        )
        ids = [step.id for step in play.steps]
        if len(ids) != len(set(ids)):
            raise PlayError("duplicate step id in %s" % play.id)
        if not play.steps:
            raise PlayError("playbook has no steps: %s" % play.id)
        return play

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "purpose": self.purpose,
            "tags": sorted(self.tags),
            "steps": [step.public() for step in self.steps],
        }


def load_playbooks(directory) -> Dict[str, Playbook]:
    """Load every *.json playbook in a directory. Standard library only."""
    root = Path(directory)
    playbooks: Dict[str, Playbook] = {}
    if not root.exists():
        return playbooks
    for path in sorted(root.rglob("*.json")):
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        play = Playbook.from_dict(payload, source=str(path))
        play.content_hash = hashlib.sha256(raw).hexdigest()
        if play.id in playbooks:
            raise PlayError("duplicate playbook id: %s" % play.id)
        playbooks[play.id] = play
    return playbooks


def _context_hash(context: dict) -> str:
    """Hash non-sensitive scalar context so approvals bind to arguments."""
    safe = {key: value for key, value in sorted(context.items())
            if key not in ("tenant", "actor", "approver")
            and isinstance(value, (str, int, float, bool))}
    payload = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity(context: dict, default_tenant="", default_actor=""):
    return (context.get("tenant") or default_tenant,
            context.get("actor") or default_actor)


class PlayEngine:
    """Plans and runs playbooks through the privacy gate and connectors."""

    def __init__(self, playbooks, connectors, privacy, audit, state=None,
                 default_tenant="", default_actor=""):
        self.playbooks = playbooks
        self.connectors = connectors
        self.privacy = privacy
        self.audit = audit
        self.state = state
        self.default_tenant = default_tenant
        self.default_actor = default_actor
        self.runs: Dict[str, dict] = {}

    def list(self) -> List[dict]:
        return [self.playbooks[key].public() for key in sorted(self.playbooks)]

    def describe(self, play_id: str) -> dict:
        return self._get(play_id).public()

    def _get(self, play_id: str) -> Playbook:
        if play_id not in self.playbooks:
            raise PlayError("unknown playbook: %s" % play_id)
        return self.playbooks[play_id]

    @staticmethod
    def action_name(play_id: str, step_id: str) -> str:
        return "play.run.%s.%s" % (play_id, step_id)

    def plan(self, play_id: str, context: dict = None) -> dict:
        """Return the steps and create single-use approval requests for gated steps."""
        play = self._get(play_id)
        context = context or {}
        tenant, actor = _identity(context, self.default_tenant, self.default_actor)
        self.audit.set_context(tenant, actor)
        args_hash = _context_hash(context)
        ttl = int(context.get("approval_ttl", 0) or 0)
        planned = []
        for step in play.steps:
            item = step.public()
            if step.approval:
                request = self.privacy.approvals.request(
                    action=self.action_name(play.id, step.id),
                    reason="%s: %s" % (play.name, step.title),
                    needs=step.needs,
                    purpose=step.purpose or play.purpose,
                    actor=actor,
                    playbook_hash=play.content_hash,
                    args_hash=args_hash,
                    ttl_seconds=ttl,
                )
                item["approval_id"] = request["approval_id"]
                item["binding"] = {
                    "actor": actor,
                    "playbook_hash": play.content_hash,
                    "args_hash": args_hash,
                }
            else:
                item["approval_id"] = ""
            planned.append(item)
        plan = {
            "play_id": play.id,
            "purpose": play.purpose,
            "playbook_hash": play.content_hash,
            "tenant": tenant,
            "actor": actor,
            "context_keys": sorted(context),
            "steps": planned,
            "next": (
                "Human grants each approval_id out-of-band, then call play.run."
            ),
        }
        self.audit.record("play.plan", "allow", play=play.id, steps=len(planned),
                          tenant=tenant, actor=actor,
                          playbook_hash=play.content_hash)
        return plan

    def privacy_check(self, play_id: str, step_id: str) -> dict:
        """Dry-run a step. Approvals are described but never consumed."""
        play = self._get(play_id)
        step = self._find_step(play, step_id)
        return {
            "play": play.id,
            "step": step.id,
            "needs": sorted(step.needs),
            "purpose": step.purpose or play.purpose,
            "write": step.write,
            "connector": step.connector,
            "scopes": sorted(step.scopes),
            "approval_required": step.approval,
            "default_allowed": all(
                need in ("aggregate", "metadata") for need in step.needs
            ) and not step.write,
        }

    @staticmethod
    def _find_step(play: Playbook, step_id: str) -> Step:
        for step in play.steps:
            if step.id == step_id:
                return step
        raise PlayError("unknown step: %s" % step_id)

    def run(self, play_id: str, approvals: Optional[dict] = None,
            context: dict = None) -> dict:
        """Execute all steps in order. Fail closed on the first denial."""
        play = self._get(play_id)
        approvals = approvals or {}
        context = context or {}
        tenant, actor = _identity(context, self.default_tenant, self.default_actor)
        self.audit.set_context(tenant, actor)
        args_hash = _context_hash(context)
        run_id = new_id("r")
        results = []

        killed = self.state.kill_check(tenant) if self.state else {"paused": False}
        if killed.get("paused"):
            reason = "kill switch active for %s: %s" % (
                killed.get("scope", "*"), killed.get("reason", ""))
            self.audit.record("play.run", "deny", play=play.id, run=run_id,
                              reason=reason)
            run = {"run_id": run_id, "play": play.id, "status": "denied",
                   "results": [{"step": "", "ok": False, "error": reason}],
                   "denied_step": ""}
            return self._finish(run, tenant, actor)

        for step in play.steps:
            if step.tool == "connectors.list":
                results.append({"step": step.id, "ok": True,
                                "connectors": self.connectors.list_public()})
                self.audit.record("play.run", "allow", play=play.id, run=run_id,
                                  step=step.id, action=step.tool)
                continue
            if step.tool == "note":
                results.append({"step": step.id, "ok": True, "note": step.title})
                self.audit.record("play.run", "allow", play=play.id, run=run_id,
                                  step=step.id, action="note")
                continue

            approval_id = approvals.get(step.id, "")
            purpose = step.purpose or play.purpose
            decision = self.privacy.check(
                tool=self.action_name(play.id, step.id),
                needs=step.needs,
                purpose=purpose,
                connector_id=step.connector,
                approval_id=approval_id,
                write=step.write,
                actor=actor,
                playbook_hash=play.content_hash,
                args_hash=args_hash,
            )
            if decision["decision"] == "deny":
                self.audit.record("play.run", "deny", play=play.id, run=run_id,
                                  step=step.id, connector=step.connector,
                                  action=step.action, needs=step.needs,
                                  reason=decision["reason"])
                results.append({"step": step.id, "ok": False,
                                "error": decision["reason"]})
                run = {"run_id": run_id, "play": play.id, "status": "denied",
                       "results": results, "denied_step": step.id}
                return self._finish(run, tenant, actor)

            try:
                call = self.connectors.call(
                    step.connector, step.action, scopes=step.scopes, needs=step.needs
                )
            except (ConnectorError, PrivacyError) as exc:
                self.audit.record("play.run", "deny", play=play.id, run=run_id,
                                  step=step.id, connector=step.connector,
                                  action=step.action, reason=str(exc))
                results.append({"step": step.id, "ok": False, "error": str(exc)})
                run = {"run_id": run_id, "play": play.id, "status": "denied",
                       "results": results, "denied_step": step.id}
                return self._finish(run, tenant, actor)

            self.audit.record(
                "play.run", "allow", play=play.id, run=run_id, step=step.id,
                connector=step.connector, action=step.action, needs=step.needs,
                purpose=purpose, approval_id=approval_id,
                approver=decision.get("approver", ""), call_id=call.get("call_id", ""),
            )
            results.append({"step": step.id, "ok": True, "result": call})

        run = {"run_id": run_id, "play": play.id, "status": "complete",
               "results": results, "context_keys": sorted(context),
               "tenant": tenant, "actor": actor}
        self.audit.record("play.run", "complete", play=play.id, run=run_id,
                          steps=len(results))
        return self._finish(run, tenant, actor)

    def _finish(self, run: dict, tenant: str, actor: str) -> dict:
        self.runs[run["run_id"]] = run
        if self.state:
            self.state.run_save(run, tenant, actor)
        return run

    def status(self, run_id: str) -> dict:
        if run_id in self.runs:
            return self.runs[run_id]
        if self.state:
            stored = self.state.run_get(run_id)
            if stored:
                return stored
        raise PlayError("unknown run id: %s" % run_id)
