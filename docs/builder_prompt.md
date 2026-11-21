# Meta-skill: build your own forward-deployed agent

Give the block below to **Claude Code, Codex, Cursor, or any coding agent** that has this repository and a shell. It reads the boilerplate, asks three questions, then builds, wires, deploys and verifies an FDA agent in your product's language. For repeat use, install `skills/fda-agent-builder/SKILL.md` as an Agent Skill.

```markdown
---
name: fda-agent-builder
description: Use when someone wants a forward-deployed agent for their product. Give this to Claude Code, Codex, Cursor or any coding agent with the FDA repo: it asks three questions, reads the boilerplate, then builds, wires, deploys and verifies the agent in the product's own language. Requires a shell, the fda CLI and this repo.
---

# Build my forward-deployed agent (meta-skill)

You are a forward-deployed engineer paired with a coding agent. The user will
paste this into **Claude Code, Codex, Cursor, or any agent with a shell and this
repository**. Your output is a working agent, not a design document.

The product can be written in **any language**. The FDA runtime is a small Python
service; the product talks to it over JSON HTTP, and real connector actions are
implemented by webhook endpoints in the product's own stack.

## 0. Read the boilerplate before doing anything

Inspect these files and follow them exactly:

- `docs/boilerplate.md` — the build contract and HTTP/handler wire format
- `examples/bundles/release-watch/` — a complete, signed-style bundle
- `integrations/claude_desktop_config.example.json` — local MCP connector
- `docs/chatgpt_and_claude.md` — remote MCP plugin setup

Do not invent endpoints, fields or CLI flags. If one of these files is missing,
stop and tell the user their checkout is incomplete.

## 1. Ask only three questions

1. **Product + agent name and language/stack?** e.g. "Acme Support, triage,
   TypeScript/Node". Derive id `acme.support-triage`.
2. **What are the 1–3 steps?** e.g. "read the error signal, open a ticket".
3. **Which systems does it touch, does it write, and who approves writes?**
   Names only — never ask for a key, token, URL or credential.

Then say: "Plan: <steps>. Writes need a human approval from <approver>. Shall I
build it?" Wait for **yes**. Ask nothing else.

## 2. Build the declarative core (same in every language)

```sh
fda agents init ./agents/<id> --id <id> --name "<Name>"
```

Write only these files:

- `fda-agent.json`: keep the scaffold; set `id`, `version: "0.1.0"`, `name`,
  `description`, `requires: {"fda": ">=0.5"}`.
- `connectors.json`: descriptors only — id, name, scopes, actions,
  `approval_required`, description. No URL, no secret, no code.
- `playbooks/<step>.json`: one play with 1–3 steps.
- `skill/SKILL.md`: keep the generated operating rules.

Minimal playbook:

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

Rules: `needs` defaults to `aggregate`; use `metadata` for ids/names;
`identifier`/`content` only with an explicit purpose. Every write gets
`write: true` and a human approval. `purpose` is one exact string — approvals
bind to its hash. Ids become `<bundle id>::<play id>` and
`<bundle id>::<connector>.<action>`.

```sh
fda agents validate ./agents/<id>
fda agents build ./agents/<id> -o dist/<id>.fda
fda agents install dist/<id>.fda
fda agents list
```

Production: build with `--sign /secure/key`, install with `--verify
--registry-check --pin`. Never put a credential or executable code in a bundle.

## 3. Wire the real product in its own language

Create `handlers.json` next to the runtime process and point `FDA_HANDLERS` at
it. This is the **only** language-agnostic bridge you need:

```json
{"acme.support-triage::tickets.create": {
  "url": "http://product-api:3000/fda/handlers/tickets.create",
  "secret_env": "FDA_HANDLER_SECRET",
  "timeout": 5
}}
```

In the product's language, add one HTTP route per key. FDA sends:

```json
{"connector":"tickets","action":"acme.support-triage::tickets.create",
 "scopes":["read","write"],"needs":["metadata"]}
```

with `X-FDA-Signature: sha256=<hmac_sha256(secret, raw_body)>`. The route
verifies the signature, calls the real service with credentials from the
product's secret manager, and returns a **small JSON object**, e.g.
`{"created": true, "ticket_ref": "INC-42"}`. Returning nothing, an error, or
timing out fails the run closed. Never echo customer content into the response.

If the stack is Python, `client.register_handler(action, fn)` is an equivalent
shortcut; do not make it a requirement.

## 4. Serve the language-agnostic API

```sh
fda api serve --port 8080 --token "$FDA_API_TOKEN"
```

The product calls, from any language:

| Call | Endpoint |
|---|---|
| discover | `GET /v1/agents`, `GET /v1/plays` |
| plan (returns approval ids) | `POST /v1/plans` `{"play_id":"<id>::<play>","context":{}}` |
| run | `POST /v1/runs` `{"play_id":"...","approvals":{"<step>":"<approval id>"}}` |
| status | `GET /v1/runs/<run_id>` |
| pending approvals | `GET /v1/approvals?status=pending` |
| human decision | `POST /v1/approvals/<id>/grant` `{"approver":"alice"}` |
| audit + brakes | `GET /v1/audit`, `GET /v1/ops/status`, `POST /v1/ops/pause` |

Send `Authorization: Bearer $FDA_API_TOKEN`, `X-FDA-Tenant` and `X-FDA-Actor`
on every call. `GET /v1/health` is public. Full wire details are in
`docs/boilerplate.md`.

## 5. Connect the humans

- **Product users:** your own UI calls the endpoints above.
- **Claude Desktop / Code:** copy
  `integrations/claude_desktop_config.example.json` (absolute `fda` path),
  restart, and upload `integrations/fda-skill.zip` once.
- **ChatGPT:** run `fda serve --transport http --host 0.0.0.0 --port 8000
  --token "$FDA_MCP_TOKEN" --no-examples` behind HTTPS, then add
  `https://<host>/mcp` as a custom MCP server plugin.
- **The same meta-skill** can be pasted into Claude/ChatGPT too — it starts at
  step 0 and rebuilds or extends the agent for another product.

## 6. Prove it works

Set `FDA_APPROVAL_MODE=external`, `FDA_STATE=/var/lib/fda/state.db`,
`FDA_HANDLERS=/path/to/handlers.json`. Ask the AI to call `agents.list`,
`plays.list`, then `play.plan`. Show the human the approval id. They grant it:

```sh
fda approvals grant <approval_id> --approver <name>
```

Then the AI calls `play.run` with `{"<step id>": "<approval id>"}`. Check:

```sh
fda ops status
fda ops audit-verify
```

Success means status `complete`, a run id, one consumed approval, and a valid
audit chain. Rehearse the brake: `fda ops pause --scope <tenant>`.

## 7. Finish

Report in four lines: bundle id + version, play id, run id + what it did, and
how to stop/revoke it (`fda ops pause`, `fda ops revoke`). If they want the long
manual path, point to `fda tutorial` and `docs/`.

## Never

- ask for or store credentials in the bundle;
- let the AI grant its own approval;
- put customer content in the audit or send it to an external model;
- make the product write Python just to use FDA;
- claim success without a run id.

```
