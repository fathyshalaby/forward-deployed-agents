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
    assert "FDA_HANDLERS" in compose, "compose must allow language-agnostic handlers"

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
    skill = read("plugins/fda-claude/skills/fda-agent-builder/SKILL.md")
    assert "fda-agent-builder" in skill, "plugin must ship the meta-skill"
    assert "embed" in skill.lower() and "mcp" in skill.lower(), \
        "meta-skill must embed into product MCP"
    builder = read("src/fda/builder_skill.py")
    assert "BUILDER_SKILL = '''---" in builder, "embedded meta-skill missing"
    assert "docs/embed_mcp.md" in builder, "meta-skill must point at embed docs"
    boilerplate = read("docs/boilerplate.md")
    assert "X-FDA-Tenant" in boilerplate, "boilerplate needs the HTTP contract"
    assert "X-FDA-Signature" in boilerplate, "boilerplate needs webhook signing"
    assert "embed_mcp.md" in boilerplate, "boilerplate must prefer embed path"
    assert "# Tutorial" in read("src/fda/tutorial.py"), "embedded tutorial missing"
    with __import__("zipfile").ZipFile(ROOT / "integrations" / "fda-skill.zip") as zf:
        assert zf.namelist() == ["fda-agent-builder/SKILL.md"], \
            "skill upload must contain only the meta-skill"
    installer = read("scripts/install_skill.py")
    assert "raw.githubusercontent.com" in installer, "installer needs GitHub raw URL"
    assert "fda-agent-builder" in installer, "installer must install the meta-skill"

    for doc in ("docs/deployment.md", "docs/security.md", "docs/integrating.md",
                "docs/chatgpt_and_claude.md",
                "docs/builder_prompt.md", "docs/boilerplate.md", "docs/install.md",
                "docs/tutorial.md", "docs/faq.md", "docs/artifacts.md",
                "docs/embed_mcp.md"):
        text = read(doc)
        assert len(text) > 500, "%s looks empty" % doc
    assert len(read("docs/README.md")) > 200, "docs/README.md looks empty"
    assert (ROOT / "examples/bundles/specky-fde/fda-agent.json").is_file(), \
        "flagship Specky example missing"
    assert (ROOT / "examples/bundles/specky-fde/artifacts/"
            "integration-health-board.md").is_file(), \
        "Specky artifact recipe missing"
    assert "artifacts.list" in read("src/fda/tools.py"), "MCP needs artifacts.list"
    assert (ROOT / "examples/embed/typescript/src/server.ts").is_file(), \
        "TypeScript embed scaffold missing"
    assert (ROOT / "examples/embed/typescript/src/control-plane.ts").is_file(), \
        "embed control plane missing"

    workflow = read(".github/workflows/ci.yml")
    assert "make all" in workflow, "CI must run make all"

    print("Deployment and integration artifacts checked")
    print("ALL CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
