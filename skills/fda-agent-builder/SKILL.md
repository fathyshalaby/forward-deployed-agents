---
name: fda-agent-builder
description: Build a forward-deployed agent for a product. Customers talk to it through Claude or ChatGPT; it onboards them, diagnoses integration issues, and acts like a forward-deployed engineer inside their boundary. Use when asked to create an FDA, customer onboarding agent, integration fixer, or Claude/ChatGPT marketplace agent for a product.
---

# Build my forward-deployed agent

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents
**Raw skill:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md
**Upload zip:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip

You turn a product into a **forward-deployed agent** that customers talk to in
Claude or ChatGPT. Give this skill to Claude Code, Codex, Cursor, or any coding
agent with this repo and a shell. The agent sits with the customer (or talks to
customer-owned systems), onboards them, diagnoses integration issues, and
proposes fixes — like a forward-deployed engineer. This repo is the factory;
the product can be any language and keeps its credentials, implementing signed
webhook handlers in its own stack.

Reference shape: `examples/bundles/specky-fde/` (onboard + integration fix for
a product like Specky). Contract: `docs/boilerplate.md`.

## Rules

1. Does it need to exist? Skip it.
2. Already in the repo? Reuse it (`examples/bundles/specky-fde/`).
3. CLI/stdlib do it? Use it.
4. Only then write the smallest thing that works.

No credentials in the bundle. No AI self-approval. No customer content in the
audit trail. End every reply with what you skipped and any risk.

## Ask only three questions

1. **Product + agent name and stack?** e.g. "Specky, customer FDE,
   TypeScript/Next". Derive id `specky.customer-fde`.
2. **What should it do for customers?** 1–3 jobs, e.g. "onboard workspace,
   diagnose broken integrations, open a ticket if it cannot fix".
3. **Which systems does it touch, does it write, and who approves writes?**
   Names only — never a key, token, URL or credential.

Say: "Plan: <jobs>. Customers will talk to this via Claude/ChatGPT. Writes need
a human approval from <approver>. Shall I build it?" Wait for **yes**.

## Build the declarative core

```sh
fda agents init ./agents/<id> --id <id> --name "<Name>"
```

Write only: `fda-agent.json`, `connectors.json`, one playbook per job under
`playbooks/`, and `skill/SKILL.md`. Copy structure from
`examples/bundles/specky-fde/`.

```json
{"id":"onboard","name":"Onboard","description":"Check workspace, list gaps, guide first connect.",
 "purpose":"onboard a customer workspace",
 "steps":[
  {"id":"status","title":"Read workspace health","tool":"connectors.call",
   "connector":"workspace","action":"workspace.status",
   "scopes":["read"],"needs":["aggregate"]},
  {"id":"gaps","title":"List missing integrations","tool":"connectors.call",
   "connector":"integrations","action":"integrations.list",
   "scopes":["read"],"needs":["metadata"]},
  {"id":"ticket","title":"Open handoff ticket if blocked","tool":"connectors.call",
   "connector":"support","action":"support.open_ticket",
   "scopes":["read","write"],"needs":["metadata"],"write":true}]}
```

Rules: start `needs` at `aggregate`; every write gets `write: true` + human
approval; `purpose` is one exact string. Installed ids are
`<bundle id>::<play id>` and `<bundle id>::<connector>.<action>`.

```sh
fda agents validate ./agents/<id>
fda agents build ./agents/<id> -o dist/<id>.fda
fda agents install dist/<id>.fda
fda agents list
```

## Wire the product (any language)

Create `handlers.json`, point `FDA_HANDLERS` at it, and add one signed webhook
route per action. Product owns credentials.

```json
{"specky.customer-fde::integrations.reconnect": {
  "url": "http://product:3000/fda/handlers/integrations.reconnect",
  "secret_env": "FDA_HANDLER_SECRET"}}
```

FDA posts `{connector, action, scopes, needs}` with
`X-FDA-Signature: sha256=<hmac(secret, raw_body)>`. Verify, call the real
system, return small JSON. Full contract: `docs/boilerplate.md`.

## Publish so customers can talk to it

- **Claude:** `fda serve --no-examples` + `integrations/claude_desktop_config.example.json`
  (or `plugins/fda-claude/`). Upload `integrations/fda-skill.zip` once for the
  operating rules. Ship the generated `skill/SKILL.md` with the connector.
- **ChatGPT / marketplace-style MCP:** `fda serve --transport http --host 0.0.0.0
  --port 8000 --token "$FDA_MCP_TOKEN" --no-examples` behind HTTPS; add
  `https://<host>/mcp` as a custom MCP server. Details:
  `docs/chatgpt_and_claude.md`.
- **Product app:** `fda api serve --port 8080 --token "$FDA_API_TOKEN"`.

## Ship a Claude artifact recipe (FDE UI)

Customers pin interactive UIs in Claude that call FDA MCP **read** tools — same
idea as connector-backed Claude artifacts. Product infra stays untouched; the
artifact lives in the customer's Claude account.

1. Add `artifacts/<job>-board.md` to the bundle (copy voice from
   `examples/bundles/specky-fde/artifacts/integration-health-board.md`).
2. Recipe must: use the real FDA connector, show scope + refresh honesty,
   read-only from the artifact, hand writes back to chat
   (`play.plan` → human approval → `play.run`).
3. After install, `artifacts.list` / `artifacts.get` expose the recipe over MCP.
4. Tell the customer: "Build the board from `artifacts.get` and pin it."

See `docs/artifacts.md`. Do not put credentials or write actions in an artifact.

Prove it with `FDA_APPROVAL_MODE=external`: `agents.list` → `plays.list` →
`play.plan` → human `fda approvals grant` → `play.run` → `fda ops audit-verify`.
Success = `complete` + run id + valid audit chain. Also call `artifacts.list`.

## Finish

Four lines: bundle id + version, play ids, how customers connect (Claude MCP /
ChatGPT MCP URL), how to stop (`fda ops pause`, `fda ops revoke`).

## Never

- ask for or store credentials in the bundle;
- let the AI grant its own approval;
- put customer content in the audit or send it to an external model;
- make the product write Python just to use FDA;
- claim success without a run id.
