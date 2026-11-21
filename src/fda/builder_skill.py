"""The single meta-skill: paste into Claude Code / Codex to build an FDA agent.

Source of truth for skills/fda-agent-builder/SKILL.md, the Claude plugin copy,
docs/builder_prompt.md, the uploadable zip, and `fda skill` (the default).
"""

BUILDER_SKILL = '''---
name: fda-agent-builder
description: Use when someone wants a forward-deployed agent for their product. Give this to Claude Code, Codex, Cursor or any coding agent with the FDA repo: it asks three questions, reads the boilerplate, then builds, wires, deploys and verifies the agent in the product's own language. Requires a shell, the fda CLI and this repo.
---

# Build my forward-deployed agent (meta-skill)

**Repo:** https://github.com/fathyshalaby/forward-deployed-agents
**Raw skill:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md
**Upload zip:** https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip

You are a forward-deployed engineer. Turn a product description into a working
agent. The product can be any language; the FDA runtime is a small service it
talks to over HTTP.

## KISS / Ponytail rules

Read `docs/boilerplate.md` and `examples/bundles/release-watch/` before writing.
Then climb this ladder, stopping at the first rung that works:

1. Does it need to exist? Skip it.
2. Is it already in the repo? Reuse it.
3. Does the CLI/stdlib do it? Use it.
4. Only then write the smallest thing that works.

No wrappers, options, config or "for later" code nobody asked for. Finish every
part the task needs. Never cut validation, security or error handling; leave one
small check for new logic. End every reply with what you skipped and any risk.

## Ask only three questions

1. **Product + agent name and stack?** e.g. "Acme Support, triage,
   TypeScript/Node". Derive id `acme.support-triage`.
2. **What are the 1–3 steps?** e.g. "read the error signal, open a ticket".
3. **Which systems does it touch, does it write, and who approves writes?**
   Names only — never a key, token, URL or credential.

Say: "Plan: <steps>. Writes need a human approval from <approver>. Shall I
build it?" Wait for **yes**. Ask nothing else.

## Build the declarative core

```sh
fda agents init ./agents/<id> --id <id> --name "<Name>"
```

Write only: `fda-agent.json` (keep the scaffold, `version: "0.1.0"`),
`connectors.json` (id, name, scopes, actions, `approval_required`), one
`playbooks/<play>.json`, and the generated `skill/SKILL.md`.

```json
{"id":"triage","name":"Triage","description":"Read a signal, open a ticket.",
 "purpose":"triage an inbound support ticket",
 "steps":[
  {"id":"signal","title":"Read signal","tool":"connectors.call",
   "connector":"tickets","action":"tickets.search",
   "scopes":["read"],"needs":["aggregate"]},
  {"id":"open","title":"Open ticket","tool":"connectors.call",
   "connector":"tickets","action":"tickets.create",
   "scopes":["read","write"],"needs":["metadata"],"write":true}]}
```

Rules: `needs` starts at `aggregate`; every write gets `write: true` and a
human approval; `purpose` is one exact string. Ids become
`<bundle id>::<play id>` and `<bundle id>::<connector>.<action>`.

```sh
fda agents validate ./agents/<id>
fda agents build ./agents/<id> -o dist/<id>.fda
fda agents install dist/<id>.fda
fda agents list
```

Production: add `--sign /secure/key`, then install with `--verify
--registry-check --pin`. No credentials or code in a bundle.

## Wire the product in its own language

Create `handlers.json`, point `FDA_HANDLERS` at it, and add one webhook route per
key in the product's language:

```json
{"acme.support-triage::tickets.create": {
  "url": "http://product-api:3000/fda/handlers/tickets.create",
  "secret_env": "FDA_HANDLER_SECRET"}}
```

FDA posts `{connector, action, scopes, needs}` with
`X-FDA-Signature: sha256=<hmac(secret, raw_body)>`. Verify it, call the real
system with credentials from the product's secret manager, and return a small
JSON object. Bad JSON, non-2xx or timeout fails closed. Full contract:
`docs/boilerplate.md`.

## Connect and prove

- **Product:** `fda api serve --port 8080 --token "$FDA_API_TOKEN"`; call
  `POST /v1/plans`, human grant, `POST /v1/runs`. Headers and endpoints are in
  `docs/boilerplate.md`.
- **Claude:** copy `integrations/claude_desktop_config.example.json` (absolute
  `fda` path), restart, upload `integrations/fda-skill.zip` once.
- **ChatGPT:** `fda serve --transport http --host 0.0.0.0 --port 8000 --token
  "$FDA_MCP_TOKEN" --no-examples` behind HTTPS, then add
  `https://<host>/mcp` as a custom MCP server.

Prove it: `FDA_APPROVAL_MODE=external`; call `agents.list`, `plays.list`,
`play.plan`; a human runs `fda approvals grant <id> --approver <name>`; then
`play.run` and `fda ops status && fda ops audit-verify`. Success is status
`complete` plus a run id and a valid audit chain.

## Finish

Four lines: bundle id + version, play id, run id + what it did, and how to stop
it (`fda ops pause`, `fda ops revoke`).

## Never

- ask for or store credentials in the bundle;
- let the AI grant its own approval;
- put customer content in the audit or send it to an external model;
- make the product write Python just to use FDA;
- claim success without a run id.
'''
