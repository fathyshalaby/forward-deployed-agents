# Authoring a playbook

A playbook is the contract between you, the customer and the agent. It states
what the agent may do, with which data and with whose permission.

## Minimal example

```json
{
  "id": "my_play",
  "name": "My play",
  "description": "One sentence on what this is for.",
  "purpose": "the purpose bound to approvals",
  "tags": ["custom"],
  "steps": [
    {
      "id": "read",
      "title": "Read an aggregate signal",
      "tool": "connectors.call",
      "connector": "observability",
      "action": "observability.get_metrics",
      "scopes": ["read"],
      "needs": ["aggregate"]
    },
    {
      "id": "change",
      "title": "Apply the approved change",
      "tool": "connectors.call",
      "connector": "tickets",
      "action": "tickets.comment",
      "scopes": ["read", "write"],
      "needs": ["metadata"],
      "write": true
    }
  ]
}
```

Save it in a directory and run with:

```sh
FDA_PLAYBOOKS=/path/to/my/playbooks python3 -m fda
```

The engine loads every `*.json` in that directory, sorted by filename. Duplicate
play ids and duplicate step ids are rejected at load time.

## Step fields

| Field | Meaning |
|---|---|
| `id` | Stable short name. Used in `approvals` maps and audit entries. |
| `title` | Human sentence shown in the plan. |
| `tool` | `connectors.list`, `connectors.call` or `note`. |
| `connector` / `action` | Required for `connectors.call`. |
| `needs` | Data classes: `aggregate`, `metadata`, `identifier`, `content`. |
| `purpose` | Overrides the playbook purpose for this step. |
| `scopes` | Must cover the needs: `read`, `write`, `identify`, `content`. |
| `write` | Any side effect. Always adds an approval gate. |
| `approval` | Gate a read explicitly. Implied by `write: true`. |

## Design rules

1. **One purpose per play.** Approvals are bound to the purpose string. Mixing
   purposes makes approvals meaningless.
2. **Read before write.** Put aggregate or metadata reads first so the human
   sees evidence before authorising a change.
3. **No content by default.** Content playbooks are possible (see
   `content_lookup.json`) but should be opt-in and reviewed by the customer.
4. **Prefer `note` for handoffs.** A note records an intent without pretending
   the agent executed something.
5. **Keep steps atomic.** One connector action per step makes denial and
   rollback understandable.

## Reviewing a playbook

Use the MCP tools rather than reading the file alone:

- `play.describe` — what would happen;
- `play.privacy_check` — data classes, scopes and gates per step;
- `play.plan` — exact approval ids to be issued;
- `play.run` — only after approvals are granted.

The demo (`python3 -m fda.demo`) shows the full lifecycle, including a
content step that is denied when no approval is supplied.
