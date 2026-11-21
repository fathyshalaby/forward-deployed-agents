# Forward-deployed agents

A **skill / prompt** that builds a forward-deployed agent **inside your product
MCP** (or scaffolds one in your stack).

Customers talk to that agent in **Claude or ChatGPT**. It onboards them,
diagnoses integration issues, and acts like a forward-deployed engineer — with
human approval on writes and a content-free audit trail.

**You keep the infrastructure.** The skill adds FDE tools to *your* MCP so you
do not need a separate FDA server. The Python runtime here is an optional
reference / local demo.

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents

## Start here: run the skill

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"
```

Or paste: [`docs/builder_prompt.md`](docs/builder_prompt.md)

```text
Use the fda-agent-builder skill to build a forward-deployed agent for my product.
```

It interviews you (stack, existing MCP or not, jobs, approvals, how customers
interact), then embeds the FDE into your MCP — or scaffolds a minimal one.

| Link | What |
|---|---|
| [Raw skill](https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md) | install / paste |
| [Embed into your MCP](docs/embed_mcp.md) | preferred production path |
| [TypeScript scaffold](examples/embed/typescript/) | copy into a product repo |
| [Specky example plays](examples/bundles/specky-fde/) | onboard + integration fix + artifact recipe |
| [Claude / ChatGPT](docs/chatgpt_and_claude.md) | point clients at **your** MCP |

## What you get

1. Declarative playbooks + connectors + optional Claude artifact recipes  
2. FDE control-plane tools on **your** MCP (`play.plan` → human grant → `play.run`)  
3. In-process connector calls using credentials you already store  
4. Setup for how customers interact (Claude, ChatGPT, artifacts)

## Try the embed scaffold (no separate FDA process)

```sh
cd examples/embed/typescript
npm install
node smoke.mjs    # plan → grant → run onboard on the in-process control plane
npm start         # stdio MCP for Claude Desktop / Code
```

## Optional: reference Python runtime

Only if you want a sidecar demo of the same policy:

```sh
python3 -m pip install .
fda agents install examples/bundles/dist/specky.customer-fde-0.1.0.fda
fda serve --no-examples
```

Prefer [`docs/embed_mcp.md`](docs/embed_mcp.md) for real products.

## Repo map

```
fda skill / docs/builder_prompt.md   front door
docs/embed_mcp.md                    embed into product MCP (default)
examples/embed/typescript/           product-owned MCP scaffold
examples/bundles/specky-fde/         declarative Specky-shaped agent
src/fda/                             optional Python reference runtime
```

```sh
make all
```
