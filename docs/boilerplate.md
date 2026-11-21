# FDA boilerplate contract

This is the short spec an AI coding agent reads before building. It is
language-agnostic: the runtime is a Python service, the product can be written
in anything.

## 1. Files to copy

| Path | Purpose |
|---|---|
| `examples/bundles/specky-fde/` | flagship bundle: onboard + integration fix |
| `integrations/claude_desktop_config.example.json` | local stdio MCP connector |
| `integrations/claude_code.mcp.example.json` | project `.mcp.json` for Claude Code |
| `docs/chatgpt_and_claude.md` | how customers talk via Claude / ChatGPT |

A bundle is `fda-agent/v1`: declarative JSON + Markdown only. No executable
Python, credentials, endpoints, symlinks, traversal or oversized files.

## 2. Bundle shape

```
agents/<bundle-id>/
  fda-agent.json          # id, version, name, description, entry, requires
  connectors.json         # descriptors only
  playbooks/<play>.json   # purpose + steps
  skill/SKILL.md          # operating rules for the AI client
```

Rules:

- ids are namespaced on install: `<bundle-id>::<play-id>` and
  `<bundle-id>::<connector>.<action>`;
- `needs` ∈ `aggregate | metadata | identifier | content`, smallest first;
- `scopes` ∈ `read | write | identify | content`;
- `write: true` always creates an approval gate;
- `purpose` is one exact string; approvals bind to its hash;
- validate → build → install → list before any product wiring.

```sh
fda agents init ./agents/<id> --id <id> --name "<Name>"
fda agents validate ./agents/<id>
fda agents build ./agents/<id> -o dist/<id>.fda
fda agents install dist/<id>.fda
fda agents list
```

Production adds `--sign`, then `--verify --registry-check --pin` on install.

## 3. JSON HTTP API (product → FDA)

Start it with `fda api serve --port 8080 --token "$FDA_API_TOKEN"`. Every call
except `/v1/health` uses:

```
Authorization: Bearer $FDA_API_TOKEN
X-FDA-Tenant: customer-42
X-FDA-Actor: support-app
Content-Type: application/json
```

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/v1/health` | — | liveness (public) |
| GET | `/v1/agents` | — | installed bundles |
| GET | `/v1/agents/{id}` | — | one bundle |
| GET | `/v1/agents/{id}/skill` | — | generated skill text |
| GET | `/v1/plays` | — | namespaced plays |
| GET | `/v1/plays/{id}` | — | one play |
| POST | `/v1/plans` | `{"play_id":"...","context":{}}` | steps + approval ids |
| POST | `/v1/runs` | `{"play_id":"...","approvals":{"step":"id"},"context":{}}` | run result |
| GET | `/v1/runs/{run_id}` | — | run status |
| GET | `/v1/approvals?status=pending` | — | pending approvals |
| POST | `/v1/approvals/{id}/grant` | `{"approver":"alice"}` | decision |
| POST | `/v1/approvals/{id}/deny` | `{"approver":"alice"}` | decision |
| GET | `/v1/audit?limit=30` | — | content-free audit |
| GET | `/v1/ops/status` | — | kill switch, stats, audit chain |
| POST | `/v1/ops/pause` | `{"scope":"acme","reason":"..."}` | paused |
| POST | `/v1/ops/resume` | `{"scope":"acme"}` | resumed |
| POST | `/v1/agents/install` | `{"archive":"...","verify":true,"pin":true}` | installed bundle |
| GET | `/v1/events?name=run.finished` | — | event history |

Flow: `POST /v1/plans` → human grant → `POST /v1/runs` → `GET /v1/runs/{run_id}`.
Approvals are for humans. Set `FDA_APPROVAL_MODE=external`; never let the AI
call the grant endpoint for itself.

## 4. Webhook handlers (FDA → product, any language)

Bundles declare capabilities; the product implements them. Point the runtime at
a small mapping file:

```sh
export FDA_HANDLERS=/etc/fda/handlers.json
export FDA_HANDLER_SECRET=<long-random-string>
```

```json
{"acme.support-triage::tickets.create": {
  "url": "http://product-api:3000/fda/handlers/tickets.create",
  "secret_env": "FDA_HANDLER_SECRET",
  "timeout": 5,
  "headers": {}
}}
```

For each key, implement one route in the product's language:

1. verify `X-FDA-Signature: sha256=<hex hmac_sha256(secret, raw_body)>`;
2. read `{connector, action, scopes, needs}`;
3. call the real system using credentials from the product secret manager;
4. return a **small JSON object** (e.g. `{"created":true,"ref":"INC-42"}`).

The runtime adds `mode`, `call_id`, `action` and `needs`. Timeouts, bad JSON,
non-2xx responses and malformed configs fail the run closed. Never return or
log customer content.

Python shortcut: `client.register_handler(action, fn)`
(or `client.register_webhook(action, url, secret=...)`).

## 5. MCP clients

- stdio: `fda serve --no-examples` — Claude Desktop / Claude Code / OpenCode.
- HTTP/SSE: `fda serve --transport http --host 0.0.0.0 --port 8000 --token ...`
  behind HTTPS — ChatGPT custom MCP plugin, claude.ai connector.

The 15 MCP tools are annotated read/write so clients ask before running
`play.run` or `approval.grant`.

## 6. Definition of done

```sh
fda doctor
fda agents list
fda ops status
fda ops audit-verify
```

One full loop: `agents.list` → `plays.list` → `play.describe` → `play.plan` →
**human grant** → `play.run` → `play.status` → `audit.explain`. Done means a
`complete` status, a run id, a consumed approval and a valid audit chain.
