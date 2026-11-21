# Deep dive: testing the different agents and how to build this properly

This is a working note, not a sales deck. It records what the prototype actually
did under different agent types and failure modes, what that proves, and what a
real build would need.

Run it yourself with `make scenarios` (10 scenarios) and `make demo`.

## 1. What I tested

The framework itself is generic. The "different agents" are playbooks plus
connectors, so the same matrix was run against four agent shapes:

| Agent shape | Example playbook | Data budget | Writes |
|---|---|---|---|
| Onboarding | `onboarding` | metadata | two, both gated |
| Support / IT fix | `support_fix` | aggregate then metadata | two, both gated |
| Access review | `access_review` | aggregate + metadata | none |
| Content investigation | `content_lookup` | content | none, but policy-gated |

Each shape was run with approvals, without approvals, and with a broken
precondition. Results from `scripts/scenarios.py`:

| Scenario | Agent | Expected | Actual | Result |
|---|---|---|---|---|
| approved | onboarding | complete | complete | PASS |
| no approval | onboarding | denied at `welcome_ticket` | denied | PASS |
| approved | support-fix | complete | complete | PASS |
| no approval | support-fix | denied at `open_issue`, after both reads | denied | PASS |
| read only | access-review | complete, no approvals | complete | PASS |
| no approval | content | denied at `search` | denied | PASS |
| approved | content | complete | complete | PASS |
| write scope removed | onboarding | denied at `welcome_ticket` | denied | PASS |
| approval with wrong purpose | onboarding | denied at `welcome_ticket` | denied | PASS |
| reused approval | onboarding | denied at `welcome_ticket` | denied | PASS |

**10/10 behaved as expected.** Every denial was written to the audit trail with
the step, connector, data classes and reason. Approved runs consumed one
single-use approval per write.

## 2. What that proves

- **Policy lives in the engine, not in the prompt.** Changing what the model
  says cannot skip a gate. The denial happens in `PrivacyGate.check` before a
  connector is called.
- **Data minimisation is enforceable.** `support_fix` reads only aggregates
  before any write; `access_review` never touches a write scope; content is
  impossible without a purpose-bound approval.
- **Approvals mean something.** They are bound to an exact action, purpose and
  set of data classes, and are single-use. Wrong-purpose and replayed approvals
  fail.
- **Capabilities come from the customer.** Removing the `write` scope from one
  connector immediately blocks the onboarding write, even with a valid approval.
- **Fail-closed is observable.** `support_fix` performs its two safe reads and
  then stops at the first gated write; no partial "success" is reported.
- **The audit is a handoff artefact.** It records decisions and denials without
  free text, so it can be reviewed without becoming a second data leak.

## 3. What it does not prove

Be blunt about this in customer conversations:

- Connectors are simulated until an operator registers real handlers. No
  ticketing, chat, repo or identity system is contacted by this repository.
- Runs, approvals and the audit trail are durable in SQLite, but this is not a
  workflow engine: no retries, queues, scheduling or rollback execution.
- `approval.grant` is deliberately disabled in `external` mode; the shipped
  approval UI is minimal. Real deployments still need SSO, TLS and a reviewed
  approver role model.
- No language model is in the loop. The tests exercise the **control plane**;
  they do not test whether an agent chooses the right play or explains itself
  well.
- Tool definitions and connector handlers are not hashed into an approval, so a
  handler swapped by an operator is not re-approved. Bundle playbooks are hashed
  and pinned; operator code is trusted by definition.
- There is no short-lived scoped token for connectors, no SIEM sink in-tree and
  no secret broker. The audit chain detects edits in the database, but a writer
  with database access can recompute it; ship entries to a write-only sink.
- There is no offline evaluation set or prompt-injection red team. The scenario
  matrix is a policy test, not a quality evaluation.
- Signatures use a shared HMAC key, not public-key non-repudiation, and there is
  no dependency resolution or compatibility check beyond the advisory
  `requires.fda` hint. See [docs/security.md](security.md).

## 4. The design choices and why

| Choice | Why | Cost |
|---|---|---|
| MCP over stdio | Standard tool surface, any client, no dependencies, easy to sandbox | No built-in auth or multi-client session model |
| JSON playbooks | Reviewable policy artefact; change workflow without changing code | No loops/branches; complex logic belongs in a new tool, not a playbook |
| Engine-side privacy gate | Works even if the model is wrong or injected | Policy must be expressed in step metadata, not prose |
| Four data classes | Small vocabulary customers can reason about | Too coarse for field-level minimisation |
| Single-use purpose-bound approvals | Stops confused-deputy and replay | Requires a real approval UX to be usable |
| Content-free audit | Audit can be shared for review without a second privacy review | Cannot reconstruct conversation context from the log alone |
| Reads before writes in playbooks | Human sees evidence before authorising change | Slightly longer approval flow |

The important pattern: **the agent reasons, the playbook constrains, the engine
enforces.** None of those three should do another one's job.

## 5. How to build it for real

### 5.1 Identity and tenancy

- Give every agent its own non-human identity. Never run it on a person's token.
- Use short-lived, audience-bound, task-scoped tokens. Carry the human principal
  as `sub` or an on-behalf-of claim so the audit can say who asked.
- Separate the agent identity, the acting user and the approver in every log
  line. "System did it" is not an audit record.

### 5.2 Connector adapters

- Keep the current shape: connector id, scopes, actions, typed small results.
  Do not return raw API payloads to the model.
- Run each connector adapter in an isolated container with an egress allowlist.
- Label every action `read`, `write` or `destructive`. Destructive actions should
  be blocked entirely in shadow mode and gated afterwards.
- Version and hash the tool definitions. Pin the reviewed hash; re-approval is
  required when a definition changes. This is the direct defence against MCP
  rug pulls.

### 5.3 Policy engine

- Keep the four data classes, but add a risk tier per step and enforce it at
  execution time, not just in the client.
- Bind approvals to **action + arguments + human principal + playbook hash**,
  not only to a purpose string. Our prototype binds action, needs and purpose;
  that is the minimum, not the destination.
- Add expiry and a maximum approval age. Add rate and spend caps where a tool can
  cost money.
- Deny by default on unknown fields, unknown connectors and schema drift.

### 5.4 Approval UX

- Show the full tool call parameters, not a friendly summary. The human must see
  what will be executed.
- Deliver approval requests where people already work (Teams, Slack, a customer
  portal), and log approval and denial immutably.
- Make the confirmation path impossible for model output to forge: the approval
  comes from the external UI, not from the agent's message.
- Write the exit criterion before the first rollout. For example: override rate
  below an agreed limit for two weeks, then promote that action from manual to
  auto. Trust is per action and per environment, and is reversible.

### 5.5 Durable state and audit

- Replace the in-memory stores with a durable run store, approval store and
  playbook registry.
- Append audit records to a write-only sink isolated from the systems being
  monitored, inside the customer boundary, with the retention the customer
  requires.
- Log identity, agent id, tool, tool-definition hash, parameters, policy
  decision, approver, result and latency. Redact secrets and PII.
- Add a kill switch that stops all runs for a tenant And test it before it is
  needed.

### 5.6 Evaluation before autonomy

- Keep `scripts/scenarios.py` as the policy regression suite. Extend it with
  every customer playbook.
- Add shadow mode: the agent decides, nothing executes, and its choices are
  compared with what a person did.
- Build an offline evaluation set with one clear expected answer per case.
  Quality, not model access, is the common blocker.
- Red team prompt injection and tool-shadowing across multiple MCP servers.
- Measure approval rate, denial rate, revert rate and data-class drift. Falling
  content use is a good sign; rising exception requests are not.

### 5.7 Agent bundles as a distribution unit

The plug-in layer in `bundle.py` turns "bring your own playbooks" into something
you can hand to another person: a versioned manifest, playbooks, connector
descriptors and an optional AI skill in one `.fda` archive. Validation rejects
unknown fields, undeclared connectors, unsafe archive paths, symlinks and
oversized files; install validates before writing to the store. Ids are namespaced
at load, so two bundles can both declare a `chat` connector.

The supply-chain controls are now part of the runtime: HMAC-signed manifests,
a publisher trust store, a local or read-only HTTP registry, pinned content
hashes, revocation and a kill switch. Bundles still never carry Python: real
adapters are registered operator-side in `ConnectorRegistry`. Signing gives
tamper detection and explicit trust, not public-key non-repudiation; the upgrade
path to asymmetric signatures is described in [docs/security.md](security.md).

### 5.8 Product sequencing

The safest first deployments are bounded, high-volume, verifiable workflows with
an obvious human fallback: internal IT/HR helpdesk, onboarding, ticket triage.
Consequential judgment stays human-only or human-in-the-loop until evidence
earns more autonomy. The sequence in `docs/rollout.md` follows that logic.

## 6. Decisions to settle with a customer

1. Which actions are `read`, `write` and `destructive` in their systems?
2. Who is the approver for each action, and what is the fallback when they are
   unavailable?
3. Is any `content` access acceptable, and for which playbooks only?
4. Where must the audit live, how long must it be kept, and who can read it?
5. Who owns and reviews playbooks after go-live?
6. What is the written exit criterion from manual approval to limited auto?
7. What is the kill switch, and who may pull it?

## 7. Sources consulted

External references checked while writing this note. They are inputs to the
design, not claims about this prototype:

- OWASP, [MCP Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html)
- Cloud Security Alliance, [Agentic MCP Security Best Practices](https://labs.cloudsecurityalliance.org/agentic/agentic-mcp-security-best-practices-v1/)
- WorkOS, [The 2026 AI agent auth checklist](https://workos.com/blog/ai-agent-auth-checklist)
- Superblocks, [12 AI agent deployment best practices](https://www.superblocks.com/blog/ai-agent-deployment-best-practices)
- CIO, [Forward-deployed engineering in the age of agentic AI](https://www.cio.com/article/4202404/forward-deployed-engineering-in-the-age-of-agentic-ai-from-vibe-coding-to-governed-autonomy.html)
- Stacklok, [MCP security best practices for enterprise deployments](https://stacklok.com/blog/mcp-security-best-practices-what-every-enterprise-team-needs-to-know-in-2026/)
