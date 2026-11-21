"""Static checks for deployment artifacts (no external dependencies)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    path = ROOT / relative
    assert path.is_file(), "missing deployment artifact: %s" % relative
    return path.read_text(encoding="utf-8")


def main():
    dockerfile = read("Dockerfile")
    assert "USER fda" in dockerfile, "Dockerfile must drop privileges"
    assert "ENTRYPOINT" in dockerfile, "Dockerfile must set an entrypoint"

    compose = read("docker-compose.yml")
    assert re.search(r"^\s+approvals:", compose, re.M), "compose needs approvals"
    assert "FDA_APPROVER_TOKEN" in compose, "compose needs an approver token"
    assert "fda-state" in compose, "compose needs a state volume"
    assert re.search(r"^\s+api:", compose, re.M), "compose needs the JSON API service"
    assert "FDA_API_TOKEN" in compose, "compose needs an API service token"

    unit = read("deploy/systemd/fda-approvals.service")
    for directive in ("User=fda", "NoNewPrivileges=true", "ProtectSystem=strict",
                      "ReadWritePaths=/var/lib/fda"):
        assert directive in unit, "systemd unit missing %s" % directive

    k8s = read("deploy/k8s/approvals.yaml")
    for kind in ("PersistentVolumeClaim", "Secret", "Deployment", "Service"):
        assert "kind: %s" % kind in k8s, "k8s manifest missing %s" % kind
    assert "runAsNonRoot: true" in k8s, "k8s manifest must run as non-root"

    api_k8s = read("deploy/k8s/api.yaml")
    for kind in ("Deployment", "Service", "Secret"):
        assert "kind: %s" % kind in api_k8s, "k8s API manifest missing %s" % kind
    assert "FDA_API_TOKEN" in api_k8s, "k8s API manifest needs a token"
    assert "runAsNonRoot: true" in api_k8s, "k8s API must run as non-root"

    mcp_http = read("src/fda/mcp_http.py")
    assert "text/event-stream" in mcp_http, "MCP HTTP transport needs SSE"
    plugin = read("plugins/fda-claude/.mcp.json")
    assert "mcpServers" in plugin, "Claude plugin needs an MCP config"
    skill = read("plugins/fda-claude/skills/fda-forward-deployed-agents/SKILL.md")
    assert "approval" in skill.lower(), "Claude skill must cover approvals"
    onboarding = read("skills/fda-onboarding-engineer/SKILL.md")
    assert "Handoff record" in onboarding, "onboarding skill needs a handoff"
    assert "fda-onboarding-engineer" in read("src/fda/onboarding_skill.py")
    assert (ROOT / "integrations" / "fda-skill.zip").is_file(), "skill upload missing"

    for doc in ("docs/deployment.md", "docs/security.md", "docs/integrating.md",
                "docs/chatgpt_and_claude.md", "docs/onboarding_prompt.md"):
        text = read(doc)
        assert len(text) > 500, "%s looks empty" % doc

    workflow = read(".github/workflows/ci.yml")
    assert "make all" in workflow, "CI must run make all"

    print("Deployment and integration artifacts checked: 16 files")
    print("ALL CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
