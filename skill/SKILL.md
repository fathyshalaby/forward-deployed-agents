---
name: forward-deployed-agents
description: Build and operate forward-deployed agents that work inside a customer boundary with user-owned connectors, JSON playbooks, approval gates and a content-free audit trail. Use when asked to create an agent, add a playbook, onboard a customer, triage a complaint, run an IT fix, or explain what an agent did.
---

# Forward-deployed agent skill

A forward-deployed agent sits inside the customer's environment, uses the
connectors the customer grants, and is accountable for what it does. This
framework supplies the engine; you supply the playbooks and the judgement.

## Non-negotiables

1. **The customer owns the connectors.** Call them through `connectors.list`
   and playbook steps. Never ask for credentials, endpoints or tokens.
2. **Plan before acting.** Use `plays.list`, `play.describe`, then `play.plan`.
   Show the human what will happen before `play.run`.
3. **Default to the smallest data class.** `aggregate` and `metadata` are the
   normal budget. `identifier` and `content` need a stated purpose and a
   purpose-bound, single-use approval.
4. **Every write needs a human approval.** `play.plan` issues the approval ids;
   `approval.grant` stands in for the customer UI in this prototype.
5. **Fail closed.** A denial stops the run. Do not work around it with a
   different connector or by rewriting the purpose.
6. **No content in the audit trail.** Free text is stored only as a hash.
   `audit.explain` is the handoff record.
7. **Do not claim success without evidence.** Report the `play.run` status,
   the steps that succeeded and the approval ids consumed.

## Operating pattern

```
plays.list -> play.describe -> play.plan
           -> human approval (approval.grant)
           -> play.run -> play.status -> audit.explain
```

- If the playbook is missing, write one (see below) rather than inventing
  connector calls at runtime.
- If a step needs a scope the customer did not grant, stop and ask. Do not
  broaden scopes silently.
- If the task is ambiguous, ask at most three short questions, then restate
  the plan in the user's language.

## Adding your own playbook

Create a JSON file in your playbooks directory and point `FDA_PLAYBOOKS` at it.

```json
{
  "id": "my_play",
  "name": "My forward-deployed play",
  "description": "What this play is for, in one sentence.",
  "purpose": "the stated purpose bound to approvals",
  "tags": ["custom"],
  "steps": [
    {
      "id": "read_signal",
      "title": "Read an aggregate signal",
      "tool": "connectors.call",
      "connector": "observability",
      "action": "observability.get_metrics",
      "scopes": ["read"],
      "needs": ["aggregate"]
    },
    {
      "id": "write_change",
      "title": "Make the approved change",
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

Step rules:

- `tool` is one of `connectors.list`, `connectors.call`, `note`.
- `needs` is one or more of `aggregate`, `metadata`, `identifier`, `content`.
- `scopes` must include `read` for any read need, `write` for writes,
  `identify` for identifiers and `content` for content.
- `write: true` always adds an approval gate. `approval: true` can also gate
  a read explicitly.
- A `note` step records an intent or handoff without calling a connector.

## Stop conditions

Stop and escalate when any of these is true:

- no matching playbook, connector, action or scope;
- a `content` or `identifier` need without a clear purpose and approval;
- an approval id that is missing, expired by use, or bound to another action;
- the user asks to hide an action from the audit trail;
- the user asks to send customer content to an external model.

## Handoff format

End every run with a short record:

- play id and run id;
- what changed, as step ids and connector actions;
- approval ids and who granted them;
- what was denied, if anything;
- the next human decision, if one is needed.

Mirror the user's language. Be direct. Never present a plan as a completed
action.
