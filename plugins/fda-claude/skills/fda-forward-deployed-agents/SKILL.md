---
name: fda-forward-deployed-agents
description: Use when a user wants to plan or run a governed agent playbook, inspect installed agents or connectors, check approvals, or explain what an agent did. Requires the FDA MCP server.
---

# Forward-deployed agents

The FDA MCP server exposes installed agent bundles as declarative playbooks.
Use its tools for every agent action; do not invent capabilities or call APIs
directly.

## Rules

1. **Never grant your own approvals.** In production `FDA_APPROVAL_MODE=external`,
   `approval.grant` always fails. A human decides in the approval UI or via
   `fda approvals grant`. Call `approval.status` to see if one is granted.
2. **Plan before running.** `play.plan` is read-only and returns step ids and
   approval ids. Show the plan to the user before executing anything.
3. **Run with explicit approvals.** Pass a map of step id → approval id to
   `play.run`. Treat a `denied` status as final; report the reason.
4. **Audit.** After a run, use `play.status` / `audit.explain` to report what
   happened. Free text is hashed, so do not expect raw payloads.

## Workflow

- `agents.list` → `agent.describe(id)` → `agent.skill(id)` to learn what is installed.
- `connectors.list` and `plays.list` → `play.describe(play_id)` to inspect a play.
- `play.privacy_check(play_id, step_id)` to see data classes and scopes without
  consuming an approval.
- `play.plan(play_id, context)` → present steps and approval ids.
- Wait for a human grant. Verify with `approval.status(approval_id)`.
- `play.run(play_id, approvals, context)` → `play.status(run_id)`.
- `ops.status` for kill switch, counters and audit-chain health.

## Failure handling

- `unknown agent/play`: run `agents.list` or `plays.list` instead of guessing ids.
- `approval required`: request it out-of-band; do not retry with a different id.
- `kill switch active`: stop and tell the user an operator paused the runtime.
- `signature/pin mismatch`: stop; the bundle was modified. Escalate to an operator.

Bundle ids are namespaced (`<bundle id>::<play id>`). Connector handlers run
inside the customer boundary; the agent only sees scopes and data classes.
