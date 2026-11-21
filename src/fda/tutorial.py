"""The end-to-end tutorial, embedded so `fda tutorial` works after pip install.

Source of truth for docs/tutorial.md.
"""

TUTORIAL = '''# Tutorial: from zero to a production forward-deployed agent

**Time:** about 45 minutes. **Result:** a signed agent bundle, real human
approvals, a durable audit trail, a product integration, and access from
ChatGPT and Claude.

The example product is "Acme Support". Replace the ids with your own as you go.

## 0. What you are building

```
product backend --SDK/HTTP--> FDA runtime --stdio--> Claude
       |                          |  |                   |
       +-- connector handlers ----+  +-- approvals UI ---+-- ChatGPT (MCP over HTTPS)
                                  |
                            SQLite state + audit
```

The agent never sees credentials, endpoints or free text. It sees connector
names, scopes and data classes. You supply the handlers; the runtime supplies
planning, approvals, audit and the kill switch.

## 1. Install and check

```sh
python3 -m pip install .
fda --version          # 0.6.0
fda doctor
```

`fda doctor` prints the state path, agent store, approval mode, trusted keys
and kill-switch state. Nothing is written to your product yet.

## 2. Run the ready-made example first

Before authoring anything, prove the loop works:

```sh
fda agents install examples/bundles/dist/demo.release-watch-1.0.0.fda
fda agents list
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\\n' | fda serve --no-examples
```

The last command prints 15 tools. Try `agents.list` and
`play.describe` with `{"play_id":"demo.release-watch::release_watch"}` through
your AI client (step 7) before writing your own bundle.

## 3. Author your own bundle

### 3.1 Scaffold

```sh
fda agents init ./agents/acme.support-triage \\
  --id acme.support-triage --name "Support Triage" \\
  --description "Triage an inbound ticket and open an approved follow-up"
```

You get `fda-agent.json`, `connectors.json`, `playbooks/`, `skill/SKILL.md`.
Only these declarative files are allowed — no executable Python, no secrets.

### 3.2 Manifest (`fda-agent.json`)

```json
{
  "schema": "fda-agent/v1",
  "id": "acme.support-triage",
  "version": "0.1.0",
  "name": "Support Triage",
  "description": "Triage a ticket; open one approved follow-up.",
  "tags": ["support", "acme"],
  "entry": {
    "playbooks": "playbooks",
    "connectors": "connectors.json",
    "skill": "skill/SKILL.md"
  },
  "requires": {"fda": ">=0.5"}
}
```

### 3.3 Connectors (`connectors.json`)

Descriptors only. Never put a URL, key or token here.

```json
[{
  "id": "tickets",
  "name": "Ticket system",
  "scopes": ["read", "write"],
  "actions": ["tickets.search", "tickets.create"],
  "approval_required": ["tickets.create"],
  "description": "Granted by the customer; called only inside our backend."
}]
```

### 3.4 Playbook (`playbooks/triage.json`)

```json
{
  "id": "triage",
  "name": "Triage an inbound ticket",
  "description": "Read an aggregate signal, then open one approved ticket.",
  "purpose": "triage an inbound support ticket",
  "steps": [
    {"id": "signal", "title": "Read the signal", "tool": "connectors.call",
     "connector": "tickets", "action": "tickets.search",
     "scopes": ["read"], "needs": ["aggregate"]},
    {"id": "open", "title": "Open the ticket", "tool": "connectors.call",
     "connector": "tickets", "action": "tickets.create",
     "scopes": ["read", "write"], "needs": ["metadata"], "write": true}
  ]
}
```

Rules that will fail validation if broken:

- `needs` is one or more of `aggregate`, `metadata`, `identifier`, `content`.
  Start at `aggregate`; `identifier`/`content` need a stated purpose and approval.
- `scopes` need `read` for reads, `write` for writes, plus `identify`/`content`
  for those data classes.
- `write: true` always creates an approval gate.
- `purpose` is one exact string. Approvals bind to its hash, so changing it
  invalidates outstanding approvals.
- Play ids become `acme.support-triage::triage` after install.

### 3.5 Skill (`skill/SKILL.md`)

Keep the generated file. It names the real playbook ids and repeats the rules:
plan first, human approves, fail closed, no content in audit.

### 3.6 Validate

```sh
fda agents validate ./agents/acme.support-triage
```

Fix the source; never loosen the validator. It rejects path traversal,
symlinks, oversized files, missing purpose and unknown data classes.

## 4. Package, sign, publish, install, pin

```sh
fda keys generate --key-id acme --publisher "Acme Inc" -o /secure/acme.key
fda keys trust /secure/acme.key
fda keys require on

fda agents build ./agents/acme.support-triage \\
  -o dist/acme.support-triage-0.1.0.fda --sign /secure/acme.key

fda registry init --registry /srv/fda/registry
fda registry publish dist/acme.support-triage-0.1.0.fda \\
  --registry /srv/fda/registry --keyfile /secure/acme.key

fda agents install dist/acme.support-triage-0.1.0.fda \\
  --verify --registry-check --registry /srv/fda/registry --pin
```

`--verify` requires a trusted signature, `--registry-check` requires a matching
registry entry, and `--pin` records the hash. A later edit to the installed
bundle fails closed at startup. Record the hash from
`fda agents describe acme.support-triage`.

## 5. Turn on real approvals

```sh
export FDA_STATE=/var/lib/fda/state.db
export FDA_AGENTS=/var/lib/fda/agents
export FDA_APPROVAL_MODE=external
export FDA_TENANT=acme
export FDA_APPROVER_TOKEN=<long-random-string>

fda doctor
fda approvals serve --token "$FDA_APPROVER_TOKEN"   # separate human process
```

The model calls `play.plan` and receives approval ids. A human grants them in
the approval UI or with `fda approvals grant <id> --approver alice@example.com`.
In `external` mode the MCP `approval.grant` tool always fails. Approvals are
single-use and bound to the action, purpose, data classes, actor, playbook hash
and argument hash.

## 6. Wire your real product APIs

Bundles are declarative; real calls live in your backend. This is the only
place credentials appear, and they come from your secret manager:

```python
from fda.sdk import Client

client = Client.create(
    state_path="/var/lib/fda/state.db",
    store="/var/lib/fda/agents",
    approval_mode="external",
    tenant="acme", actor="product-app",
)

client.register_handler(
    "acme.support-triage::tickets.create",
    lambda ctx: ticket_api.create_ref(ctx["needs"]),
)

scoped = client.as_tenant("customer-42", actor="support-app")
plan = scoped.plan("acme.support-triage::triage", {"ticket": "INC-42"})
# a human grants plan["steps"][1]["approval_id"] in your UI
approvals = {"open": plan["steps"][1]["approval_id"]}
result = scoped.run("acme.support-triage::triage", approvals)
assert result.ok, result.results
```

Handlers receive only `{connector, action, scopes, needs}` and return a small
dict. Never log free text or send customer content to an external model. If
your product is not Python, use `FDA_HANDLERS` instead: map the same action to
an HTTP endpoint in your own language and verify `X-FDA-Signature`. See
[boilerplate.md](boilerplate.md) for the exact contract.

## 7. Drive it from AI clients

### Claude Desktop / Code

Copy `integrations/claude_desktop_config.example.json` into
`~/Library/Application Support/Claude/claude_desktop_config.json`, using the
absolute path to `fda`. Restart Claude. Upload `integrations/fda-skill.zip`
once under Customize → Skills. Ask it to call `agents.list`.

### ChatGPT

Expose MCP over HTTPS:

```sh
fda serve --transport http --host 0.0.0.0 --port 8000 \\
  --token "$FDA_MCP_TOKEN" --no-examples
```

In ChatGPT web: Plugins → `+` → Add custom MCP server → Server URL
`https://<host>/mcp` → protocol SSE or streaming HTTP → create and install the
plugin. Full MCP requires Business/Enterprise/Edu. Then `@` the plugin and ask
it to plan the play; grant the approval in your own UI before it runs.

### Your own product

```sh
fda api serve --port 8080 --token "$FDA_API_TOKEN"
curl -H 'Authorization: Bearer token' -H 'X-FDA-Tenant: customer-42' \\
     -H 'Content-Type: application/json' \\
     -d '{"play_id":"acme.support-triage::triage"}' \\
     http://localhost:8080/v1/plans
```

## 8. Deploy it

Choose one:

```sh
# Docker: approvals + JSON API + remote MCP + stdio MCP
docker compose up -d approvals api mcp-http

# systemd: hardened approval UI
sudo cp deploy/systemd/fda-approvals.service /etc/systemd/system/
sudo systemctl enable --now fda-approvals

# Kubernetes: two manifests, replace placeholder Secrets first
kubectl apply -f deploy/k8s/approvals.yaml -f deploy/k8s/api.yaml
```

Put TLS in front of every HTTP surface. Keep one API replica (SQLite has one
writer). `docs/deployment.md` has the env-var table and runbook.

## 9. Verify and operate

```sh
fda ops status
fda ops audit-verify            # exit 1 if any entry was edited
fda approvals list --status pending
```

Drive one full loop: `agents.list` → `plays.list` → `play.describe` →
`play.plan` → human grant → `play.run` → `play.status` → `audit.explain`.
Confirm the run status is `complete`, the approval was consumed once, and the
audit chain verifies.

Rehearse the brakes:

```sh
fda ops pause --scope acme --reason onboarding-test
# a run must be denied before any connector is called
fda ops resume --scope acme
fda ops revoke acme.support-triage --version 0.1.0 --reason compromised
```

Never report success without a run id and a verified audit entry.

## 10. Let the meta-skill do it for you

Once you understand the loop, hand steps 3–9 to Claude Code, Codex or any coding
agent:

```sh
fda skill                        # prints the one meta-skill
```

Paste it with a product description. It reads `docs/boilerplate.md`, asks three
questions, scaffolds the bundle, writes language-agnostic webhook handlers,
signs and pins it, deploys, connects the AI clients and verifies the run. The
same text is installable from `skills/fda-agent-builder/SKILL.md` and is bundled
in `integrations/fda-skill.zip`. The older `fda skill onboarding` prompt remains
available for the longer interview format.

## Troubleshooting

| Symptom | Fix |
|---|---|
| no agents listed | `fda agents list`; check `FDA_AGENTS` in the server process |
| `approval.grant` fails | expected in external mode; use the UI or CLI |
| content step denied | add a purpose and a purpose-bound approval |
| ChatGPT cannot add server | HTTPS required; check SSE choice; Business+ for full MCP |
| Claude shows no tools | absolute command path, valid JSON, full app restart |
| pin mismatch | bundle was edited; rebuild and reinstall, do not bypass |
| kill switch active | an operator paused the tenant; `fda ops status` |

## Next

- [Architecture](architecture.md) — why the layers are separated
- [Security](security.md) — trust model and honest limits
- [Integration](integrating.md) — SDK, HTTP API, events, tenancy
- [ChatGPT and Claude](chatgpt_and_claude.md) — client-specific setup
- [Deployment](deployment.md) — production runbook
'''
