# Rollout pattern

Forward deployment is an operating model, not a feature flag. Start narrow and
earn each additional permission.

| Phase | What the agent may do | Exit condition |
|---|---|---|
| 0. Shadow | Read-only playbooks; humans do the work | Playbook reviewed; audit matches reality |
| 1. Onboarding | Run onboarding playbooks with approvals | Customer accepts handover quality |
| 2. Diagnose | Aggregate and metadata reads across systems | Evidence summaries trusted by support |
| 3. Gated fixes | Writes, one approval each, with rollback notes | Denial rate and revert rate acceptable |
| 4. Broader plays | Customer-authored playbooks in production | Customer maintains its own library |

## What to measure

- **Approval rate** — how often a gated step is approved; low rates mean the
  play asks for too much.
- **Denial rate** — how often the engine blocks a step; high rates mean the
  playbook or connector descriptors need fixing.
- **Revert rate** — how often a human undoes an agent action.
- **Data-class drift** — count of `identifier` and `content` steps over time.
  It should go down, not up.
- **Handoff clarity** — whether `audit.explain` alone answers "what did it do?".

## Operating rules

- Every new playbook starts in shadow mode.
- Every write step has an owner and a rollback note.
- Approval grants are attributable to a human role, never to "system".
- Content playbooks require a separate customer decision.
- The audit trail is append-only and lives inside the customer boundary.

## Prototype limitations

Runs and play status are in memory. Connectors are simulated. The approval
grant tool is a demo. Real deployment needs durable state, real adapters, a
customer approval UI and a write-only audit sink.
