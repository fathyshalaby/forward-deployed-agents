# Privacy model

Privacy is enforced by the engine, not by the agent's good intentions.

## Data classes

| Class | Examples | Default |
|---|---|---|
| `aggregate` | counts, rates, summaries | allowed with `read` scope |
| `metadata` | ticket id, team, role, status | allowed with `read` scope |
| `identifier` | account or person id | purpose + approval + `identify` scope |
| `content` | messages, comments, free text | purpose + approval + `content` scope |

`aggregate` and `metadata` are the normal budget. A playbook that needs more
must say so in its step definition, and the human sees that requirement in
`play.describe` and `play.plan`.

## Approvals

- `play.plan` creates one **single-use, purpose-bound** approval per gated step.
- `approval.grant` is a demo stand-in for the customer's approval UI. In
  production, replace the tool but keep `ApprovalStore.consume`: it checks that
  the approval was granted, matches the exact action and purpose, covers all
  requested data classes, and has not been used.
- Writing always requires approval, even when the data class is only
  `metadata`. The gate fails closed if an approval id is missing.

## Audit

`AuditLog.record` writes only: timestamp, tool, decision, connector, action,
data classes, purpose, approval id, approver and simulated call id. Free text
is hashed with SHA-256 and truncated; emails, token-shaped strings and bearer
headers are redacted. `audit.explain` is the human-readable handoff.

The default audit path is `data/runtime/audit.jsonl`, which is gitignored.
Point `FDA_AUDIT` at a write-only store inside the customer boundary.

## Connector boundary

- The agent never receives credentials. It names a connector, action and
  scopes; the adapter executes inside the customer boundary.
- `ConnectorRegistry.call` refuses unknown connectors, ungranted actions and
  ungranted scopes.
- Simulated results carry no user payloads. Real adapters should return the
  same small, typed shapes rather than raw responses.

## What this does not claim

This is a prototype, not a certified privacy system. It does not claim
differential privacy, k-anonymity or formal verification. It demonstrates a
specific discipline: minimal data classes, purpose-bound human approvals, a
fail-closed engine and an audit trail that cannot contain content. The same
discipline was applied to the Enron case in the sibling repository; see
[from_enron_case.md](from_enron_case.md).
