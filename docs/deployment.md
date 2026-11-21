# Deployment guide

This guide turns the framework into a service you can hand to a customer. The
runtime has no third-party dependencies; SQLite is the only state backend.

## 1. What runs where

| Process | Command | Purpose |
|---|---|---|
| MCP server | `fda serve` | stdio JSON-RPC; the AI client launches it |
| Approval UI | `fda approvals serve` | loopback HTTP where humans grant/deny |
| JSON API | `fda api serve` | HTTP for product integrations (any language) |
| Operator CLI | `fda ...` | install, trust, pin, revoke, pause, inspect |

All three services share one SQLite file (`FDA_STATE`). They do not share an
address space: the model never sees the approver token, so it cannot grant its
own approvals. The JSON API is the integration surface for your own product;
see [integrating.md](integrating.md).

```
AI client --stdio--> fda serve -------+
product backend --HTTP--> fda api ----+--same SQLite--> runs / approvals / audit
                                      |                     ^
human browser --HTTP--> fda approvals -+                     |
```

## 2. First-time setup on a customer host

```sh
python3 -m pip install .                 # or: docker build -t fda .
export FDA_STATE=/var/lib/fda/state.db
export FDA_AGENTS=/var/lib/fda/agents
export FDA_AUDIT=/var/lib/fda/audit.jsonl
export FDA_APPROVAL_MODE=external         # the model cannot grant approvals
export FDA_TENANT=acme                    # recorded on every audit entry

fda doctor                               # verify paths and trust configuration
```

All paths are overridable:

| Variable | Default | Meaning |
|---|---|---|
| `FDA_STATE` | `~/.fda/state.db` | SQLite: runs, approvals, audit, pins, revocations, kill switch |
| `FDA_AGENTS` | `~/.fda/agents` | Installed agent bundle store |
| `FDA_AUDIT` | checkout `data/runtime/audit.jsonl`, else `~/.fda/audit.jsonl` | Optional mirrored JSONL audit |
| `FDA_APPROVAL_MODE` | `demo` | Set `external` in production |
| `FDA_TENANT` / `FDA_ACTOR` | empty | Default identity written to the audit trail |
| `FDA_NO_EXAMPLES` | unset | Set `1` to hide checkout example playbooks |
| `FDA_CONNECTORS` / `FDA_PLAYBOOKS` | checkout examples | Single-agent `serve --single` overrides |
| `FDA_TRUST` | `~/.fda/trust.json` | Trusted publisher keys |
| `FDA_REGISTRY` | `~/.fda/registry` | Local registry directory or read-only HTTP(S) index URL |
| `FDA_REQUIRE_SIGNATURE` | unset | Set `1` to require a trusted signature on every install |
| `FDA_SIGNING_KEY` | `~/.fda/keys/default.key` | Default key for `agents build --sign` |
| `FDA_APPROVER_TOKEN` | empty | Approver token for `approvals serve` |
| `FDA_API_TOKEN` | empty | Shared bearer token required by `api serve` |
| `FDA_MCP_TOKEN` | empty | Bearer token for `serve --transport http` (ChatGPT/remote MCP) |
| `FDA_ACTOR` | empty | Default actor for SDK/API calls |

## 3. Trust and supply chain

```sh
# Publisher (once)
fda keys generate --key-id acme --publisher "Acme Inc" -o /secure/acme.key

# Customer (once): the trust entry contains the shared signing secret
fda keys trust /secure/acme.key --trust /etc/fda/trust.json
fda keys require on --trust /etc/fda/trust.json

# Publisher: build and sign
fda agents build ./agent -o dist/acme.agent-1.0.0.fda --sign /secure/acme.key
fda registry init --registry /srv/fda/registry
fda registry publish dist/acme.agent-1.0.0.fda \
    --registry /srv/fda/registry --trust /etc/fda/trust.json --keyfile /secure/acme.key

# Customer: verify signature, registry entry and hash, then pin
fda agents install dist/acme.agent-1.0.0.fda \
    --verify --registry-check --registry /srv/fda/registry \
    --trust /etc/fda/trust.json --pin
```

Pinning means any later edit to the installed bundle is a hard failure at
startup, not a silent change in behaviour. See [docs/security.md](security.md)
for the trust model and its limits.

## 4. Approvals

In `external` mode `approval.grant` over MCP always fails. Grant from the
approval UI or CLI instead:

```sh
fda approvals serve --state /var/lib/fda/state.db \
    --token "$FDA_APPROVER_TOKEN" --host 127.0.0.1 --port 8787
```

Endpoints (all except `/health` require `X-FDA-Token`):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/approvals?status=pending` | Queue |
| `GET` | `/approvals/<id>` | One request with its exact bindings |
| `POST` | `/approvals/<id>/grant` | `{"approver": "alice"}` |
| `POST` | `/approvals/<id>/deny` | `{"approver": "alice"}` |

CLI equivalent:

```sh
fda approvals list --status pending
fda approvals grant <approval_id> --approver alice
fda approvals deny <approval_id> --approver alice
```

Approvals are bound to the action, purpose, data classes, actor, playbook hash
and argument hash. They are single-use and can expire with `approval_ttl` on
`play.plan`/`play.run`. Decisions are atomic across processes.

## 5. Product integration API

For products that are not AI clients (or that want a server-side integration),
run the JSON API instead of or alongside the MCP server:

```sh
fda api serve --host 0.0.0.0 --port 8080 \
    --state /var/lib/fda/state.db --approval-mode external \
    --token "$FDA_API_TOKEN"
```

Calls require `Authorization: Bearer $FDA_API_TOKEN`; `GET /v1/health` is public.
Send `X-FDA-Tenant` and `X-FDA-Actor` headers so every audit entry carries the
end-user identity. Full endpoint list and SDK usage are in
[integrating.md](integrating.md). Keep approval grants in your authenticated
approver path, never in model-generated code.

## 6. Operating

```sh
fda ops status                           # counters, kill switch, audit chain
fda ops pause --scope '*' --reason 'incident-123'
fda ops resume --scope acme
fda ops revoke acme.agent --version 1.0.0 --reason compromised
fda registry revoke acme.agent --version 1.0.0 --reason compromised
fda ops audit-verify                     # exit 1 if any entry was edited
fda agents skill acme.agent --target opencode
fda serve --state /var/lib/fda/state.db --approval-mode external
```

Kill switch scopes are `*` (all tenants) or a tenant id. A paused tenant gets a
`denied` run before any connector is called, and the reason is audited.

## 7. Containers and systemd

- `Dockerfile` builds a non-root image whose entrypoint is `fda`; use
  `docker run -i --rm` for the stdio server.
- `docker-compose.yml` runs the approval UI and the JSON API with persistent
  volumes for state, agents, trust and registry. Set `FDA_APPROVER_TOKEN`,
  `FDA_API_TOKEN` and `FDA_MCP_TOKEN` before `docker compose up`. The `mcp-http`
  service is the remote MCP endpoint for ChatGPT / remote Claude.
- `deploy/systemd/fda-approvals.service` is a hardened unit for the approval UI.
  Create `/etc/fda/approvals.env` mode `0600` containing
  `FDA_APPROVER_TOKEN=<long random string>`, then `systemctl enable --now
  fda-approvals`.
- `deploy/k8s/approvals.yaml` and `deploy/k8s/api.yaml` are minimal
  Deployment/Service manifests for Kubernetes; replace the placeholder Secret
  tokens before applying. The API runs one replica because SQLite has a single
  writer; shard by tenant or move to a shared store before scaling out.

Example container invocation:

```sh
docker run -i --rm \
  -v fda-state:/var/lib/fda -v fda-agents:/var/lib/fda/agents \
  -e FDA_STATE=/var/lib/fda/state.db \
  -e FDA_AGENTS=/var/lib/fda/agents \
  -e FDA_APPROVAL_MODE=external \
  fda:latest serve --no-examples
```

## 8. Production checklist

- [ ] `FDA_APPROVAL_MODE=external`; the approver token is not given to the AI client.
- [ ] `FDA_API_TOKEN` is a long random string; the API is behind TLS/SSO.
- [ ] Real operator-side adapters registered with `ConnectorRegistry.register_handler`.
- [ ] Signatures required; publisher keys protected; registry checked on install.
- [ ] Bundle hashes pinned after review; revocation runbook tested.
- [ ] Audit chain verified on a schedule and shipped to a write-only sink.
- [ ] Kill switch tested; named owner for `*`, tenant and bundle revocation.
- [ ] Data-class classification confirmed per connector (`read`/`identify`/`content`).
- [ ] `fda doctor` and `make all` green in CI.

## 9. What is still a prototype

Connectors ship as descriptors plus operator handlers; there is no OAuth broker
or secret store in this repository. HMAC signing gives tamper detection and
explicit trust, not public-key non-repudiation. The audit hash chain detects
edits in the SQLite file but an operator with write access can recompute it;
ship entries to a write-only sink for real tamper evidence. Runs are recorded
but not a full durable workflow engine (no retries, queues or cron).
