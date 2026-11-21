"""Repository check: docs links, playbook loading and content-free audit."""
import json
import re
from pathlib import Path

from fda.runtime import load_runtime

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("SECRET_CANARY", "private.user@example.com", "ghp_canarytoken")


def check_links():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\((?!https?://)([^)#]+)", readme)
    missing = [link for link in links if not (ROOT / link).exists()]
    assert not missing, "broken README links: %s" % missing
    return len(links)


def check_audit():
    runtime = load_runtime(persist_audit=False)
    plan = runtime.engine.plan("onboarding", {"role": "support"})
    approvals = {}
    for step in plan["steps"]:
        if step["approval_id"]:
            runtime.approvals.grant(step["approval_id"], "check-human")
            approvals[step["id"]] = step["approval_id"]
    runtime.engine.run("onboarding", approvals)
    # A content step without approval must be denied and recorded.
    runtime.engine.run("content_lookup")
    # A canary string never enters the audit trail as itself.
    runtime.audit.record("check", "allow", text="SECRET_CANARY user private.user@example.com")
    blob = json.dumps(runtime.audit.explain(limit=50), sort_keys=True)
    assert "SECRET_CANARY" not in blob
    assert "private.user@example.com" not in blob
    assert runtime.audit.entries[-1]["text_hash"]
    return len(runtime.audit.entries)


def main():
    links = check_links()
    entries = check_audit()
    print("README links checked: %d" % links)
    print("Audit entries checked: %d" % entries)
    print("ALL CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
