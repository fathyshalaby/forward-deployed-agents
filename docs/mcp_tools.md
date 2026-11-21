# MCP tool reference

The server advertises fifteen tools through `tools/list`. All calls use
`tools/call` with `{"name": ..., "arguments": {...}}`. Every tool is read-only
except `approval.grant` (demo mode only), `play.run` and `play.privacy_check`
(which never consumes an approval).

| Tool | Purpose | Notes |
|---|---|---|
| `connectors.list` | List granted connectors | Shows id, scopes, actions and approval requirements; no credentials |
| `plays.list` | List playbooks | Includes installed bundles whose ids are namespaced |
| `play.describe` | Inspect one playbook | Steps, data classes, scopes, gates and playbook hash |
| `play.plan` | Prepare a run | Issues approval ids bound to actor, playbook hash and arguments |
| `play.run` | Execute a playbook | Pass `approvals` as `{"step_id": "approval_id"}`; accepts `tenant`/`actor`/`approval_ttl` |
| `play.status` | Look up a run by id | Durable in SQLite when `FDA_STATE` is configured |
| `play.privacy_check` | Dry-run one step | Does not consume approvals |
| `approval.request` | Create a custom approval | Bound to action, needs and purpose |
| `approval.grant` | Grant an approval | Always fails in `FDA_APPROVAL_MODE=external`; use the approval UI |
| `approval.status` | Inspect an approval | Shows bindings, status, approver and expiry |
| `audit.explain` | Explain what happened | Hash-chained, tenancy-aware; free text appears only as a hash |
| `agents.list` | List installed agent bundles | Includes version, playbook ids, connectors and signature state |
| `agent.describe` | Describe one bundle | Read-only; accepts namespaced `agent_id` |
| `agent.skill` | Return a bundle's AI skill markdown | Save it into a client skills directory |
| `ops.status` | Operational health | Approval mode, kill switch, counters and audit-chain verification |

## Example session

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"plays.list","arguments":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"play.plan","arguments":{"play_id":"onboarding"}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"agents.list","arguments":{}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"ops.status","arguments":{}}}
```

Errors in tool execution are returned as `isError: true` with a text message.
Protocol errors use standard JSON-RPC codes. Notifications are acknowledged on
stderr and receive no response.
