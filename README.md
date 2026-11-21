# Forward-deployed agents

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents

A **skill / prompt** that builds a forward-deployed agent for your product.

Your customers talk to that agent in **Claude or ChatGPT**. It onboards them,
diagnoses integration issues, and acts like a forward-deployed engineer —
inside their boundary, with human approval on every write, and a content-free
audit trail.

This repo is the factory. Your product keeps the credentials and implements
signed webhook handlers in whatever language it already uses.

## Start here: run the skill

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"
```

Or paste the prompt: [`docs/builder_prompt.md`](docs/builder_prompt.md)

Then say:

```text
Use the fda-agent-builder skill to build a forward-deployed agent for my product.
```

It asks three questions (product/stack, 1–3 customer jobs, systems + who
approves writes), then scaffolds the bundle, wires handlers, and connects
Claude / ChatGPT MCP.

| Link | What |
|---|---|
| [Raw skill](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md) | install / paste |
| [Claude zip](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip) | upload as a Claude skill |
| [Contract](docs/boilerplate.md) | HTTP API + webhook wire format |
| [Claude / ChatGPT](docs/chatgpt_and_claude.md) | how customers talk to the agent |
| [Install](docs/install.md) | skill installer options |

## What you get

1. A declarative `fda-agent/v1` bundle (playbooks + connector descriptors + skill).
2. Product-side webhook stubs in your stack (no Python required in the product).
3. An MCP / JSON API surface so Claude, ChatGPT, or your app can drive it.
4. External human approvals + content-free audit trail.

Flagship example: [`examples/bundles/specky-fde/`](examples/bundles/specky-fde/)
— onboard + integration fix for a product like Specky.

## Try the example in 30 seconds

```sh
python3 -m pip install .
fda doctor
fda agents install examples/bundles/dist/specky.customer-fde-0.1.0.fda
fda agents list
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' | fda serve --no-examples
```

## Production sketch

```sh
export FDA_STATE=/var/lib/fda/state.db
export FDA_AGENTS=/var/lib/fda/agents
export FDA_APPROVAL_MODE=external
export FDA_HANDLERS=/etc/fda/handlers.json

fda approvals serve --token "$FDA_APPROVER_TOKEN"
docker compose up -d approvals api mcp-http
fda ops status && fda ops audit-verify
```

See [`docs/deployment.md`](docs/deployment.md) and [`docs/security.md`](docs/security.md).

## Repo map

```
fda skill / docs/builder_prompt.md   the front door (same text)
skills/fda-agent-builder/            installable skill
examples/bundles/specky-fde/         reference agent (onboard + fix)
docs/boilerplate.md                  wire contract the skill follows
src/fda/                             runtime: MCP, HTTP API, approvals, audit
plugins/fda-claude/                  Claude connector + the skill
```

```sh
make all    # tests, scenarios, docs and deploy checks
```
