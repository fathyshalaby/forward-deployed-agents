# Architecture

The framework is deliberately small. It does not know what onboarding, support
or IT support mean. It knows how to describe work, check it, run it through
customer-owned connectors and explain what happened.

```
   user / agent   product backend   other services
        |                |                |
        | MCP stdio      | Python SDK     | JSON HTTP
        v                v                v
  +---------------------------------------------------+
  | mcp.py / sdk.py / http_api.py   adapters          |
  | tools.py                        generic tool set  |
  +---------------------------------------------------+
        |
        v
  +-----------------------------------+
  | bundle.py     installed agents    |  <- versioned .fda bundles
  |   validate -> namespace -> load   |
  +-----------------------------------+
         |              |
         v              v
  security.py      store.py
  sign / trust     runs / approvals / audit
  registry / pins  revocations / kill switch
         |              |
         +-----> plays.py <------+
                 playbook engine     <- your JSON playbooks
                 plan -> approval -> run -> log
                      |       |        |
                      v       v        v
             connectors.py  privacy.py  audit
             user-owned     data budget content-free
             capabilities   + approvals record

  approval_ui.py  separate token-gated HTTP process, shared SQLite
```

## Trust boundary

- The agent runs **inside the customer's environment**. Production connectors
  make calls there; no customer data is copied to the framework operator.
- Connectors are described by id, scopes and actions. Credentials, hosts and
  payloads are never exposed to the agent or written to the audit log.
- The simulated connectors in `examples/connectors.json` return only small,
  non-sensitive result dictionaries. Replace them with real adapters.
- The model can plan, run and inspect, but in `external` approval mode it cannot
  grant an approval: the approver token lives in a different process.

## Why MCP and why stdio

MCP gives the agent a standard tool surface (`tools/list`, `tools/call`) that
works with any MCP client. stdio keeps the server dependency-free and easy to
sandbox: one JSON message per line, protocol on stdout, diagnostics on stderr.

## Why JSON playbooks

A playbook is a policy artefact, not code. It can be reviewed, diffed and
approved by the customer before the agent ever runs it. Changing a workflow
does not require changing the engine. Python hooks are unnecessary for the
common case: the language model does the reasoning; the playbook constrains the
actions.

## Extension points

| Want | Do |
|---|---|
| New workflow | Add a JSON playbook; set `FDA_PLAYBOOKS`, or ship a bundle |
| Ship an agent to a user | `python3 -m fda agents init` then `build [--sign key]` |
| Install someone's agent | `python3 -m fda agents install [--verify --pin] agent.fda` |
| Trust a publisher | `fda keys generate`, `fda keys trust`, `fda keys require on` |
| Distribute bundles | `fda registry init` and `fda registry publish` |
| New system to act on | Add a connector descriptor and register a real adapter |
| Stricter data rules | Extend `privacy.py`; keep `play.plan` as the dry-run surface |
| Real human approval | Run `fda approvals serve`; use `external` mode |
| Durable audit | `FDA_STATE` for SQLite; ship entries to a write-only sink |
| Emergency stop | `fda ops pause --scope '*' --reason ...` |
| Embed in a Python product | `from fda.sdk import Client; Client.create(...)` |
| Embed in any other stack | `python3 -m fda api serve` and call `/v1/*` |
| React to runs in your own UI | `client.on("approval.requested", cb)` or a signed webhook |
| Give an AI client the rules | `python3 -m fda agents skill <id> --target opencode` |

Bundles stay declarative: they cannot ship Python, credentials or endpoints.
Ids are namespaced on load, so independent bundles cannot shadow each other.
See [integrating.md](integrating.md) for product embedding,
[deployment.md](deployment.md) and [security.md](security.md) for the production
model.

See [playbook_authoring.md](playbook_authoring.md),
[agent_bundles.md](agent_bundles.md), [connect_an_ai.md](connect_an_ai.md) and
[privacy_model.md](privacy_model.md).
