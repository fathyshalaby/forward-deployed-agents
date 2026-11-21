# MCP tool reference

The server advertises ten tools through `tools/list`. All calls use
`tools/call` with `{"name": ..., "arguments": {...}}`.

| Tool | Purpose | Notes |
|---|---|---|
| `connectors.list` | List granted connectors | Shows id, scopes, actions and approval requirements; no credentials |
| `plays.list` | List playbooks | Reads your playbook directory |
| `play.describe` | Inspect one playbook | Steps, data classes, scopes and gates |
| `play.plan` | Prepare a run | Issues approval ids; executes nothing |
| `play.run` | Execute a playbook | Pass `approvals` as `{"step_id": "approval_id"}` |
| `play.status` | Look up a run by id | In-memory for this prototype |
| `play.privacy_check` | Dry-run one step | Does not consume approvals |
| `approval.request` | Create a custom approval | Bound to action, needs and purpose |
| `approval.grant` | Simulate human grant | Demo only; replace with customer UI |
| `audit.explain` | Explain what happened | Content appears only as a hash |

## Example session

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"plays.list","arguments":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"play.plan","arguments":{"play_id":"onboarding"}}}
```

Errors in tool execution are returned as `isError: true` with a text message.
Protocol errors use standard JSON-RPC codes. Notifications are acknowledged on
stderr and receive no response.
