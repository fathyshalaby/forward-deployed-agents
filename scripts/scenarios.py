"""Exercise the framework across the different agent types and failure modes.

Run: python3 scripts/scenarios.py (or make scenarios)
"""
from dataclasses import dataclass
from typing import Callable, List

from fda.connectors import Connector
from fda.runtime import load_runtime

from tests.helpers import fresh_runtime, run_play


@dataclass
class Scenario:
    name: str
    agent: str
    expectation: str
    runner: Callable


def _play(play_id, grant=True, mutate=None):
    def run():
        runtime = fresh_runtime()
        if mutate:
            mutate(runtime)
        return run_play(runtime, play_id, grant=grant), runtime
    return run


def _drop_write(runtime):
    connector = runtime.connectors.get("tickets")
    runtime.connectors.register(Connector(
        id=connector.id, name=connector.name,
        scopes=[scope for scope in connector.scopes if scope != "write"],
        actions=connector.actions, description=connector.description,
        approval_required=connector.approval_required,
    ))


def _wrong_purpose(runtime):
    plan = runtime.engine.plan("onboarding")
    approval_id = runtime.approvals.request(
        "play.run.onboarding.welcome_ticket", "test", ["metadata"], "wrong purpose",
    )["approval_id"]
    runtime.approvals.grant(approval_id, "test-human")
    runtime._wrong_approval = approval_id
    runtime._plan = plan


def _run_wrong_purpose():
    runtime = fresh_runtime()
    _wrong_purpose(runtime)
    approvals = {}
    for step in runtime._plan["steps"]:
        if step["approval_id"]:
            runtime.approvals.grant(step["approval_id"], "test-human")
            approvals[step["id"]] = step["approval_id"]
    approvals["welcome_ticket"] = runtime._wrong_approval
    return runtime.engine.run("onboarding", approvals), runtime


def _run_reused_approval():
    runtime = fresh_runtime()
    plan = runtime.engine.plan("onboarding")
    approvals = {}
    for step in plan["steps"]:
        if step["approval_id"]:
            runtime.approvals.grant(step["approval_id"], "test-human")
            approvals[step["id"]] = step["approval_id"]
    first = runtime.engine.run("onboarding", approvals)
    second = runtime.engine.run("onboarding", approvals)
    return second, runtime


SCENARIOS: List[Scenario] = [
    Scenario("onboarding / approved", "onboarding", "complete",
             _play("onboarding", grant=True)),
    Scenario("onboarding / no approval", "onboarding", "denied",
             _play("onboarding", grant=False)),
    Scenario("support-fix / approved", "support_fix", "complete",
             _play("support_fix", grant=True)),
    Scenario("support-fix / no approval", "support_fix", "denied",
             _play("support_fix", grant=False)),
    Scenario("access-review / read only", "access_review", "complete",
             _play("access_review", grant=False)),
    Scenario("content / no approval", "content_lookup", "denied",
             _play("content_lookup", grant=False)),
    Scenario("content / approved", "content_lookup", "complete",
             _play("content_lookup", grant=True)),
    Scenario("onboarding / write scope removed", "onboarding", "denied",
             _play("onboarding", grant=True, mutate=_drop_write)),
    Scenario("approval / wrong purpose", "onboarding", "denied",
             _run_wrong_purpose),
    Scenario("approval / reused", "onboarding", "denied",
             _run_reused_approval),
]


def _needs(run):
    classes = set()
    for result in run["results"]:
        for need in result.get("result", {}).get("needs", []):
            classes.add(need)
    return ",".join(sorted(classes)) or "-"


def main():
    rows = []
    passed = 0
    for scenario in SCENARIOS:
        run, runtime = scenario.runner()
        actual = run["status"]
        ok = actual == scenario.expectation
        passed += int(ok)
        denials = [entry for entry in runtime.audit.entries
                   if entry.get("decision") == "deny"]
        rows.append({
            "scenario": scenario.name,
            "agent": scenario.agent,
            "expected": scenario.expectation,
            "actual": actual,
            "result": "PASS" if ok else "FAIL",
            "denied_step": run.get("denied_step", "-"),
            "data_classes": _needs(run),
            "audit_denials": len(denials),
        })

    widths = {key: max(len(key), *(len(str(row[key])) for row in rows))
              for key in rows[0]}
    fmt = lambda key: "%%-%ds" % widths[key]
    header = "  ".join(fmt(key) % key for key in rows[0])
    print(header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(fmt(key) % row[key] for key in row))
    print("\n%d/%d scenarios behaved as expected." % (passed, len(rows)))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
