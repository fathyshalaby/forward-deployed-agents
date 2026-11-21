# Forward-deployed agents

Build an agent that works **inside a customer boundary**, using connectors the
customer owns. It plans, asks a human for approval, runs, and leaves a
content-free audit trail. Standard library only; one SQLite file.

## The easy way: give this to Claude Code or Codex

There is **one meta-skill**. Paste it into Claude Code, Codex, Cursor, or any
coding agent with this repo and a shell. It asks three questions, reads our
boilerplate, then builds, wires, deploys and verifies a complete agent in the
product's own language.

```sh
fda skill          # print the meta-skill (same as: fda skill builder, fda meta)
```

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents

Install the skill directly from GitHub, no checkout needed:

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"
```

Or grab the files directly:

- [Raw meta-skill](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md)
- [Claude upload zip](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip)
- [Copy/paste prompt](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/docs/builder_prompt.md)
- [Claude plugin](https://github.com/fathyshalaby/forward-deployed-agents/tree/main/plugins/fda-claude)
- Full guide: [`docs/install.md`](docs/install.md)

The product does **not** have to be Python. FDA runs as a small service; the
product calls its JSON API, and real connector actions are signed webhook
routes implemented in whatever stack the product uses. See
[`docs/boilerplate.md`](docs/boilerplate.md) for the complete wire contract.

### What the skill does

1. Asks: product + stack, 1–3 steps, systems touched + who approves writes.
2. Scaffolds a declarative `fda-agent/v1` bundle — no code, no credentials.
3. Validates, builds, installs and lists the agent.
4. Writes `handlers.json` and generates product-side webhook routes.
5. Starts the JSON API / MCP server and connects Claude or ChatGPT.
6. Runs one approved play, checks the audit chain, and reports how to stop it.

## Install in 30 seconds

```sh
python3 -m pip install .
fda doctor
fda agents install examples/bundles/dist/demo.release-watch-1.0.0.fda
fda agents list
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | fda serve --no-examples
```

That last command shows 15 tools. Point an MCP client at `fda serve`, or use the
meta-skill to generate your own agent instead of the example.

## Talk to the agent

| Client | Command / config |
|---|---|
| Claude Desktop / Code | [`integrations/claude_desktop_config.example.json`](integrations/claude_desktop_config.example.json) or [`plugins/fda-claude/`](plugins/fda-claude/) |
| ChatGPT | `fda serve --transport http --host 0.0.0.0 --port 8000 --token "$FDA_MCP_TOKEN" --no-examples` behind HTTPS, then add `https://<host>/mcp` as a custom MCP server |
| Any product | `fda api serve --port 8080 --token "$FDA_API_TOKEN"` — JSON HTTP, no Python required |

Details: [`docs/chatgpt_and_claude.md`](docs/chatgpt_and_claude.md).

## Production in one block

```sh
export FDA_STATE=/var/lib/fda/state.db
export FDA_AGENTS=/var/lib/fda/agents
export FDA_APPROVAL_MODE=external      # the AI cannot approve its own work
export FDA_HANDLERS=/etc/fda/handlers.json

fda approvals serve --token "$FDA_APPROVER_TOKEN"   # separate human process
docker compose up -d approvals api mcp-http
fda ops status && fda ops audit-verify
```

Signing, registry checks, pinning, revocation, kill switch, tenancy and
container/systemd/Kubernetes files are included. See
[`docs/deployment.md`](docs/deployment.md) and [`docs/security.md`](docs/security.md).

## Repo map

```
fda skill              the one meta-skill
docs/boilerplate.md    the contract the skill follows
docs/                  longer reference (tutorial, security, integration, ...)
examples/bundles/      a complete example agent
src/fda/               runtime, MCP, HTTP API, bundles, state, trust, CLI
plugins/fda-claude/    Claude connector + the meta-skill
```

Humans who want the long path can read the
[45-minute tutorial](docs/tutorial.md) or the [FAQ](docs/faq.md). Everything
else in `docs/` is reference material, not required reading.

## Check

```sh
make all             # tests, scenarios, docs and deploy checks
make tutorial        # optional long-form walkthrough
```
