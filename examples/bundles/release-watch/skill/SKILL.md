---
name: release-watch
description: Watch deploy signals and, after human approval, post a short update to the on-call channel. Use when asked to check a release, summarise deploy health or notify on-call.
---

# Release Watch

An example forward-deployed agent shipped as an installable bundle. Its ids are
namespaced as `demo.release-watch::...` when installed, so it cannot collide with
another agent's `chat` connector or `release_watch` play.

## Non-negotiables

1. Use the customer's connectors. Never ask for endpoints, tokens or credentials.
2. Call `agents.list`, then `play.describe`, then `play.plan` before any run.
3. Show the plan to a human. Approve the `notify` step before `play.run`.
4. Fail closed. If the engine denies a step, stop and report it.
5. Keep free text out of the audit trail; `audit.explain` is the handoff record.

## Play

- `demo.release-watch::release_watch`

## Steps

1. `status` — aggregate deploy signal, no approval.
2. `owner` — metadata about recent events, no approval.
3. `notify` — a write to the on-call channel; always needs a purpose-bound,
   single-use approval from `play.plan`.

## Handoff

Report the run id, status, the step ids that succeeded, the approval id consumed
and anything that was denied. Never present a plan as a completed action.
