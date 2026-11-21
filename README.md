# Forward-deployed agents

A small, general framework for agents that work **inside a customer boundary**,
using **connectors the customer owns**. It is not tied to onboarding, support or
IT operations: those are example playbooks you can replace.

The agent plans work, asks a human for purpose-bound approvals, runs through
granted connectors, and produces a content-free audit trail. Python 3 standard
library only.

```
playbooks (JSON)  ->  plan  ->  human approval  ->  run  ->  audit.explain
                          \-> deny and stop
```

## Quick start

```sh
make test          # 32 unittest tests
make demo          # scripted end-to-end session
make scenarios     # 10 scenario matrix across the different agent types
make serve         # MCP stdio server: python3 -m fda
```

In an MCP client, point the server at `python3 -m fda` from this directory.

## What is included

- **MCP server** (`src/fda/mcp.py`, `tools.py`): JSON-RPC over stdio, ten tools,
  no dependencies.
- **Playbook engine** (`src/fda/plays.py`): load JSON playbooks, plan, gate and
  run them. Unknown playbooks, steps, connectors or scopes fail closed.
- **Privacy gate** (`src/fda/privacy.py`): four data classes, read/write scopes,
  single-use purpose-bound approvals, redacted append-only audit.
- **User-owned connectors** (`src/fda/connectors.py`): descriptors expose only
  id, scopes and actions. Credentials never reach the agent.
- **Example playbooks** (`examples/playbooks/`): onboarding, support-to-fix,
  access review and a content step that demonstrates denial.
- **Agent skill** (`skill/SKILL.md`): operating rules and a template for new
  playbooks.
- **Scenario matrix** (`scripts/scenarios.py`): 10 runs covering approval,
  no-approval, missing scope, wrong-purpose and replayed approvals.
- **Docs** (`docs/`): architecture, authoring, privacy, tool reference, rollout,
  a [deep dive](docs/deep_dive.md) on what the prototype proves and how to build
  it for real, and the lessons carried from the Enron case.

## Your own agent

```sh
mkdir -p my-playbooks
cp examples/playbooks/onboarding.json my-playbooks/
FDA_PLAYBOOKS=/absolute/path/to/my-playbooks python3 -m fda
```

Add connector descriptors in your own JSON file and set `FDA_CONNECTORS`.
See [docs/playbook_authoring.md](docs/playbook_authoring.md) for the step
schema.

## Safety model

| Rule | Enforcement |
|---|---|
| Smallest data class | `needs` declared per step; `aggregate`/`metadata` default |
| Writes need a human | `write: true` forces an approval gate |
| Content is exceptional | `content` needs purpose, approval and scope |
| No credential exposure | connector public view excludes secrets and endpoints |
| No content in audit | free text hashed; emails and tokens redacted |
| Fail closed | first denial stops the run |

See [docs/privacy_model.md](docs/privacy_model.md). This is a prototype: runs
are in memory, connectors are simulated and `approval.grant` stands in for the
customer approval UI.

## Repo layout

```
src/fda/           engine, MCP server, privacy, connectors, demo
examples/          connector descriptors and example playbooks
skill/SKILL.md     reusable agent skill
docs/              architecture, authoring, privacy, tools, rollout
tests/             standard-library unittest suite
```

## Why this shape

The Enron case next door proved the value of minimal data, explicit decisions
and tested risk claims. This framework applies the same discipline to live
customer work: the playbook is the decision, the gate is the test, and the
audit is the evidence. See [docs/from_enron_case.md](docs/from_enron_case.md).
