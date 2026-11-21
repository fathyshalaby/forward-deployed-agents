# Architecture

The framework is deliberately small. It does not know what onboarding, support
or IT support mean. It knows how to describe work, check it, run it through
customer-owned connectors and explain what happened.

```
   user / agent
        |
        | MCP JSON-RPC over stdio
        v
  +-----------------------------------+
  | mcp.py        protocol boundary   |
  | tools.py      generic tool set    |
  +-----------------------------------+
        |
        v
  +-----------------------------------+
  | plays.py      playbook engine     |  <- your JSON playbooks
  |   plan -> approval -> run -> log  |
  +-----------------------------------+
        |            |           |
        v            v           v
  connectors.py  privacy.py    audit
  user-owned     data budget   content-free
  capabilities   + approvals   record
```

## Trust boundary

- The agent runs **inside the customer's environment**. Production connectors
  make calls there; no customer data is copied to the framework operator.
- Connectors are described by id, scopes and actions. Credentials, hosts and
  payloads are never exposed to the agent or written to the audit log.
- The simulated connectors in `examples/connectors.json` return only small,
  non-sensitive result dictionaries. Replace them with real adapters.

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
| New workflow | Add a JSON playbook; set `FDA_PLAYBOOKS` |
| New system to act on | Add a connector descriptor and a real adapter |
| Stricter data rules | Extend `privacy.py`; keep `play.plan` as the dry-run surface |
| Real human approval | Replace `approval.grant` with your customer UI; keep `ApprovalStore.consume` |
| Durable audit | Point `FDA_AUDIT` at a write-only store inside the boundary |

See [playbook_authoring.md](playbook_authoring.md) and
[privacy_model.md](privacy_model.md).
