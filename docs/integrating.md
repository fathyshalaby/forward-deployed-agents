# Integrate agents into your product

The framework is a library first. MCP and the CLI are adapters around the same
runtime, so your product can offer agents without asking users to install an AI
client. There are two integration surfaces:

| Surface | Use when |
|---|---|
| Python SDK (`fda.sdk`) | Your backend is Python or you want in-process control |
| JSON HTTP API (`fda api serve`) | Your backend is another language or you want a separate service |

Both use the same SQLite state file, approval rules, audit trail and security
controls. See [deployment.md](deployment.md) for production setup and
[security.md](security.md) for the trust model.

## 1. Python SDK

```python
from fda.sdk import Client, Config

client = Client.create(Config(
    state_path="/var/lib/fda/state.db",
    store="/var/lib/fda/agents",
    approval_mode="external",
    tenant="acme",
    actor="web-app",
))

# Your product decides when a play is relevant.
plans = client.list_plays()
plan = client.plan("onboarding", {"ticket": "INC-42"})

# Push approval ids into your own UI; grant only after a real human decides.
approval_id = plan["steps"][0]["approval_id"]
client.grant_approval(approval_id, approver="alice@example.com")

result = client.run("onboarding",
                    approvals={"welcome_ticket": approval_id},
                    {"ticket": "INC-42"})
if result.ok:
    audit = client.audit(limit=20)
```

`Client` methods:

| Method | Purpose |
|---|---|
| `list_agents()`, `describe_agent(id)`, `agent_skill(id)` | Browse installed bundles |
| `install_agent(path, verify=..., registry_check=..., pin=...)` | Add a bundle at runtime |
| `list_plays()`, `describe_play(id)` | Browse playbooks |
| `plan(play_id, context)` | Issue approval ids; execute nothing |
| `run(play_id, approvals, context)` | Execute; returns `RunResult` with `.ok` |
| `status(run_id)` | Look up a durable run |
| `privacy_check(...)` | Dry-run one step without consuming approvals |
| `pending_approvals()`, `approval_status(id)` | Approval queue for your UI |
| `request_approval(...)`, `grant_approval(id, who)`, `deny_approval(id, who)` | Out-of-band decisions |
| `register_connector(...)`, `register_handler(action, fn)` | Bind real adapters |
| `audit(limit)`, `verify_audit()`, `ops_status()` | Evidence and health |
| `pause(scope, reason)`, `resume(scope)`, `revoke_agent(id)` | Emergency controls |
| `as_tenant(tenant, actor)` | Scoped view; every call and audit entry carries it |

`grant_approval`/`deny_approval` are the privileged path: call them from your
product's authenticated approver endpoint, never from model-generated code. In
`external` mode the MCP `approval.grant` tool is disabled.

### Your own playbooks and connectors

If you do not want bundles, point the SDK at your own files:

```python
client = Client.from_paths(
    "/srv/app/playbooks",
    connectors_path="/srv/app/connectors.json",
    state_path="/var/lib/fda/state.db",
    approval_mode="external",
)
```

Register a real adapter instead of the simulated result:

```python
client.register_connector(
    "tickets", "Ticket system", ["read", "write"], ["tickets.create"],
    handler=lambda ctx: my_ticket_api.create(entity=ctx["needs"]),
)
# or bind one action explicitly, including a namespaced bundle action:
client.register_handler("acme.agent::chat.post", my_chat_api.post)
```

The handler receives only `{connector, action, scopes, needs}` — no credentials
and no free text. It must return a small JSON-serialisable dict.

For a product that is not Python, skip the callable. Point `FDA_HANDLERS` at a
JSON map of action → webhook URL and implement one route per action in your own
language. FDA signs the raw body with `X-FDA-Signature`; the full request and
response contract is in [boilerplate.md](boilerplate.md). In Python you can also
use `client.register_webhook(action, url, secret=...)`.

### Tenancy

Create one scoped view per request. The tenant and actor are written to the
audit trail and used for per-tenant kill switch checks:

```python
tenant_client = client.as_tenant(request.tenant_id, actor=request.user_id)
result = tenant_client.run("onboarding")
```

Revoking a tenant is `tenant_client.pause(tenant_client.tenant, "offboarded")`.

## 2. Events and webhooks

Subscribe in-process:

```python
client.on("approval.requested", lambda event: push_to_ui(event.to_dict()))
client.on("run.denied", alert_operator)
client.on("*", log_to_your_metrics)
```

Event names: `approval.requested`, `approval.granted`, `approval.denied`,
`play.planned`, `run.started`, `run.finished`, `run.denied`, `ops.paused`,
`ops.resumed`, `agent.installed`, `agent.revoked`. A failing subscriber is
recorded in `client.events.errors` and never breaks a run.

Forward events to another service with a signed webhook:

```python
from fda.sdk import WebhookSink

WebhookSink("https://internal.example.com/fda-events",
            secret=os.environ["FDA_WEBHOOK_SECRET"],
            events=["approval.requested", "run.denied"],
            bus=client.events)
```

The receiver verifies `X-FDA-Signature: sha256=<hex hmac of the raw body>` with
the shared secret. Deliveries are synchronous with a short timeout; failures
land in `sink.errors` and can be retried by your job queue.

## 3. JSON HTTP API

Start it as a separate service:

```sh
fda api serve --host 0.0.0.0 --port 8080 \
  --token "$FDA_API_TOKEN" --approval-mode external
```

Authenticate with `Authorization: Bearer $FDA_API_TOKEN`. `GET /v1/health` is
public for load balancers. Send `X-FDA-Tenant` and `X-FDA-Actor` headers to scope
a request. Denied runs return HTTP 403; invalid input returns 400.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/health` | Liveness |
| `GET` | `/v1/agents`, `/v1/agents/{id}`, `/v1/agents/{id}/skill` | Installed bundles |
| `GET` | `/v1/plays`, `/v1/plays/{id}` | Playbooks |
| `POST` | `/v1/plans` | `{"play_id", "context"}` → approval ids |
| `POST` | `/v1/runs` | `{"play_id", "approvals", "context"}` → run |
| `GET` | `/v1/runs/{id}` | Durable run |
| `GET` | `/v1/approvals?status=pending` | Approval queue |
| `POST` | `/v1/approvals/{id}/grant` | `{"approver": "alice"}` |
| `POST` | `/v1/approvals/{id}/deny` | `{"approver": "alice"}` |
| `GET` | `/v1/audit?limit=50` | Content-free audit timeline |
| `GET` | `/v1/ops/status`, `/v1/events` | Health and event history |
| `POST` | `/v1/ops/pause`, `/v1/ops/resume` | `{"scope", "reason"}` |
| `POST` | `/v1/agents/install` | `{"archive", "verify", "pin"}` (privileged) |

Example:

```sh
curl -s -X POST http://localhost:8080/v1/plans \
  -H 'Authorization: Bearer token' -H 'X-FDA-Tenant: acme' \
  -H 'Content-Type: application/json' \
  -d '{"play_id":"onboarding","context":{"ticket":"INC-42"}}'
```

The HTTP API is a plain JSON adapter. Put your existing SSO, rate limiting and
TLS in front of it; `--token` is a shared service token, not an end-user identity.

## 4. Product checklist

- Mount a durable `FDA_STATE` volume and back it up.
- Use `approval_mode="external"` and grant only through your authenticated UI.
- Bind every action you allow to a real handler; never install unsigned bundles
  in a production tenant (`verify=True`, `registry_check=True`, `pin=True`).
- Scope every request with `as_tenant` / `X-FDA-Tenant`.
- Ship audit entries to a write-only sink and run `verify_audit()` on a schedule.
- Subscribe to `run.denied` and `approval.requested` so nothing waits silently.
- Rehearse `pause("*")` and `revoke_agent` before go-live.

A runnable example lives in
[examples/integrations/product_app.py](../examples/integrations/product_app.py).
