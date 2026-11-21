"""The single meta-skill: paste into Claude / Codex / Cursor to build an FDA.

Source of truth for skills/fda-agent-builder/SKILL.md, the Claude plugin copy,
docs/builder_prompt.md, the uploadable zip, and `fda skill` (the default).
"""

BUILDER_SKILL = '''---
name: fda-agent-builder
description: Build a forward-deployed agent inside a product team's own MCP (or scaffold one). Customers talk through Claude or ChatGPT; the product keeps infra and credentials. Use when asked for an FDA, customer onboarding agent, integration fixer, or to add FDE tools to an existing MCP.
---

# Build my forward-deployed agent (into YOUR MCP)

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents
**Raw skill:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md
**Upload zip:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip

You are a forward-deployed engineer helping a **product team**. Give this skill
to Claude Code, Codex, Cursor, or any coding agent with this repo and a shell.
Goal: a customer FDE agent they ship on **their** infrastructure — preferably
as tools on **their existing MCP server**. Customers talk via Claude or ChatGPT.
The product keeps credentials and deploys nothing separate unless they choose to.

**Default path: embed into the product MCP.** Do **not** require a separate
`fda serve` deploy. The Python `fda` runtime in this repo is an optional
reference / local demo only.

Read first: `docs/embed_mcp.md`, `examples/embed/typescript/`,
`examples/bundles/specky-fde/`.

## Rules

1. Does it need to exist? Skip it.
2. Already in their repo or this repo? Reuse it.
3. Extend their MCP before inventing a new process.
4. Only then write the smallest thing that works.

No credentials in playbooks. No AI self-approval. No customer content in the
audit trail. End every reply with what you skipped and any risk.

## Interview (ask these, then stop)

Ask in the user's language. Skip any answer already obvious from the repo.

1. **Product + agent name + stack?** e.g. "Specky, customer FDE, TypeScript/Next".
   Derive id `specky.customer-fde`.
2. **MCP today?**  
   - Already have one → where (path / package), transport (stdio / HTTP), how
     Claude/ChatGPT connect.  
   - None → "I'll scaffold a minimal MCP in your stack and register the FDE
     tools there." Confirm language/runtime.
3. **Customer jobs (1–3)?** e.g. onboard workspace, diagnose integrations, open
   a ticket if blocked.
4. **Systems + writes + who approves writes?** Names only — never keys/tokens/URLs.
5. **How should customers interact?** Pick one primary: Claude Desktop connector,
   ChatGPT custom MCP, Claude artifacts on those tools, and/or in-product chat.
6. **Approvals:** who grants writes (role), and UI (in-app button, Slack, email
   link, CLI)? Default: human out-of-band; model never self-grants.

Restate: "Plan: embed FDE tools into <their MCP or new scaffold>. Jobs: …
Writes approved by … Customers reach it via … Shall I build it?" Wait for
**yes**.

## What you build (in THEIR repo)

### A. Declarative core (any language)

Same shape as `examples/bundles/specky-fde/`:

- `fda-agent.json` — id, version, name, entry
- `connectors.json` — descriptors only (no credentials)
- `playbooks/*.json` — purpose + steps; every write has `write: true`
- `skill/SKILL.md` — operating rules for the AI client
- `artifacts/*.md` — optional Claude artifact recipes (read-only UI)

Copy structure from the Specky example; adapt ids and actions to their product.

### B. Control plane ON their MCP

Add these tools to **their** MCP server (names can be prefixed with `fda.` if
they already collide). Contract: `docs/embed_mcp.md`.

| Tool | Role |
|---|---|
| `agents.list` / `agent.describe` | installed agent metadata |
| `plays.list` / `play.describe` / `play.plan` | plan before act |
| `play.run` | execute with approval map; fail closed |
| `approval.status` (+ grant only via human path, not the model) |
| `audit.explain` / `ops.status` | content-free trail + kill switch |
| `artifacts.list` / `artifacts.get` | Claude artifact recipes |

Implement connectors as **in-process calls** into the product (DB, OAuth tokens
already in their secret store). No separate webhook hop required when the MCP
runs inside the product boundary.

Scaffold: `examples/embed/typescript/` (Node MCP). For other stacks, mirror the
same tool schemas and policy rules in their language.

If they have **no** MCP: create a minimal server in-repo (stdio and/or HTTP/SSE),
register FDE + any product tools, and write the Claude Desktop /
`chatgpt` connector config pointing at **that** server.

### C. Interaction setup

Walk them through the primary channel they chose:

- Claude Desktop / Code: mcp config → their server command or URL
- ChatGPT: HTTPS MCP URL for their server
- Artifacts: recipe that uses **read** tools only; writes stay in chat with
  `play.plan` → human approval → `play.run`
- Approvals: wire the human grant path they picked (never `approval.grant` from
  the model in production)

### D. Prove it

One loop on **their** MCP: `agents.list` → `plays.list` → `play.plan` → human
grant → `play.run` → `audit.explain`. Success = `complete` + run id + audit
entry. Also open `artifacts.get` if they shipped a recipe.

## Optional: reference Python runtime

Only if they explicitly want a sidecar: `pip install` this repo and
`fda serve`. Prefer embed. Do not present the sidecar as required.

## Finish

Report: agent id, MCP path (file or URL), how customers connect, approval path,
how to pause/kill, what you skipped.

## Never

- require a separate FDA MCP deploy when their product can host the tools;
- ask for or store credentials in playbooks;
- let the AI grant its own approval in production;
- put customer content in the audit or send it to an external model;
- claim success without a run id on their server.
'''
