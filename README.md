# Forward-deployed agents

A small, general framework for agents that work **inside a customer boundary**,
using **connectors the customer owns**. It is not tied to onboarding, support or
IT operations: those are example playbooks you can replace.

The agent plans work, asks a human for purpose-bound approvals, runs through
granted connectors, and produces a content-free, hash-chained audit trail.
Python 3 standard library only; durable state lives in one SQLite file.

```
playbooks (JSON)  ->  plan  ->  out-of-band approval  ->  run  ->  audit
                            \-> deny and stop
```

## Build an agent, ship it, plug it in

An **agent bundle** is one versioned folder (or one `.fda` archive) with your
playbooks, connector descriptors and optional AI skill. A builder creates it; a
user installs it and points their AI client at the MCP server. Ids are
namespaced, so several independently authored agents can run side by side.

```sh
# builder
python3 -m fda agents init ./my-agent --id acme.my-agent --name "My Agent"
python3 -m fda agents validate ./my-agent
python3 -m fda agents build ./my-agent -o dist/acme.my-agent-0.1.0.fda

# user
python3 -m fda agents install dist/acme.my-agent-0.1.0.fda
python3 -m fda agents list
python3 -m fda agents skill acme.my-agent --target opencode
python3 -m fda serve
```

See [docs/agent_bundles.md](docs/agent_bundles.md) to author a bundle and
[docs/connect_an_ai.md](docs/connect_an_ai.md) to connect OpenCode, Claude or
any MCP client. A complete example is in
[examples/bundles/release-watch](examples/bundles/release-watch), with a ready
archive at `examples/bundles/dist/`.

## Deploy it

```sh
python3 -m pip install .
export FDA_STATE=/var/lib/fda/state.db
export FDA_AGENTS=/var/lib/fda/agents
export FDA_APPROVAL_MODE=external        # the model cannot grant its own approvals
export FDA_TENANT=acme

fda doctor
fda approvals serve --token "$FDA_APPROVER_TOKEN"   # separate human process
fda serve --state "$FDA_STATE" --approval-mode external
```

Signatures, registry checks, pinning, revocation, a kill switch, tenancy-aware
audit and container/systemd/Kubernetes artifacts are included. Start with
[docs/deployment.md](docs/deployment.md) and [docs/security.md](docs/security.md).

```sh
docker build -t fda .
docker compose up -d approvals             # human approval UI on 127.0.0.1:8787
docker compose run --rm fda                # MCP stdio server
```

## Quick start (the framework)

```sh
make test          # 55 unittest tests
make demo          # scripted end-to-end session
make scenarios     # 10 scenario matrix across the different agent types
make check         # docs links and content-free audit
make check-deploy  # container, systemd and Kubernetes artifacts
make serve         # MCP stdio server: python3 -m fda serve
```

In an MCP client, point the server at `python3 -m fda serve` from this
directory, or `pip install .` and use `fda serve`.

## Integrate it into your own product

The MCP server is one adapter; the same runtime is a Python SDK and a JSON HTTP
API, so your product can offer agents without an AI client.

```python
from fda.sdk import Client

client = Client.create(approval_mode="external", tenant="acme", actor="web-app")
plan = client.plan("onboarding")
client.grant_approval(plan["steps"][0]["approval_id"], "alice")  # your UI
result = client.run("onboarding", {"welcome_ticket": plan["steps"][0]["approval_id"]})
```

```sh
fda api serve --port 8080 --token "$FDA_API_TOKEN"   # any language via HTTP
make integration-example                            # runnable product example
```

See [docs/integrating.md](docs/integrating.md) for the SDK, HTTP endpoints,
events/webhooks, custom connectors and multi-tenancy. A runnable example is in
[examples/integrations/product_app.py](examples/integrations/product_app.py).

## What is included

- **Agent bundles** (`src/fda/bundle.py`, `cli.py`): scaffold, validate, package,
  sign, install, list, export a skill; namespaced so bundles cannot collide.
- **Embedding SDK and JSON API** (`src/fda/sdk.py`, `http_api.py`): in-process
  Python client, HTTP adapter, events, signed webhooks and tenant scoping.
- **MCP server** (`src/fda/mcp.py`, `tools.py`): JSON-RPC over stdio, fifteen
  tools, no runtime dependencies.
- **Playbook engine** (`src/fda/plays.py`): load JSON playbooks, plan, gate and
  run them. Unknown playbooks, steps, connectors or scopes fail closed.
- **Privacy gate** (`src/fda/privacy.py`): four data classes, read/write scopes,
  single-use approvals bound to actor, playbook hash and arguments.
- **Durable state** (`src/fda/store.py`): SQLite runs, approvals, hash-chained
  audit, revocations, pins and a global/per-tenant kill switch.
- **Trust and supply chain** (`src/fda/security.py`): signed bundles, publisher
  keyring, local or read-only HTTP registry, content pinning.
- **Out-of-band approvals** (`src/fda/approval_ui.py`): token-protected HTTP UI
  and CLI; model-side grants are disabled in `external` mode.
- **User-owned connectors** (`src/fda/connectors.py`): descriptors expose only
  id, scopes and actions. Credentials never reach the agent. Real adapters are
  registered operator-side per action.
- **Example playbooks** (`examples/playbooks/`): onboarding, support-to-fix,
  access review and a content step that demonstrates denial.
- **Example bundle** (`examples/bundles/release-watch/`): a third-party-style
  agent with its own connector, write gate and AI skill.
- **Agent skill** (`skill/SKILL.md`): framework operating rules and a template
  for new playbooks.
- **Scenario matrix** (`scripts/scenarios.py`): 10 runs covering approval,
  no-approval, missing scope, wrong-purpose and replayed approvals.
- **Docs** (`docs/`): architecture, authoring, bundles, connecting an AI,
  integration, privacy, tools, deployment, security, rollout and a
  [deep dive](docs/deep_dive.md).

## Your own agent without bundles

```sh
mkdir -p my-playbooks
cp examples/playbooks/onboarding.json my-playbooks/
FDA_PLAYBOOKS=/absolute/path/to/my-playbooks python3 -m fda serve --single
```

Add connector descriptors in your own JSON file and set `FDA_CONNECTORS`.
Bundles are the recommended route when you intend to hand an agent to someone
else; see [docs/playbook_authoring.md](docs/playbook_authoring.md) for the step
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
| Bundles carry no code | declarative JSON/Markdown only; safe extraction on install |
| No bundle id collisions | all ids namespaced with `<bundle id>::` |
| Trusted publishers only | HMAC signatures, trust store, optional required signatures |
| No silent upgrades | registry hash check and content pinning |
| Emergency stop | global or per-tenant kill switch checked before every run |
| Attributable decisions | approvals bound to actor, purpose and playbook hash |

See [docs/privacy_model.md](docs/privacy_model.md) and
[docs/security.md](docs/security.md). Connectors are simulated until an
operator registers real handlers; the audit chain detects edits in the database,
so production should also ship entries to a write-only sink.

## Repo layout

```
src/fda/           engine, MCP server, bundles, state, trust, approvals, CLI
examples/          connector descriptors, example playbooks, example bundle
skill/SKILL.md     reusable framework skill
docs/              architecture, authoring, bundles, connect-an-AI, privacy, tools,
                   deployment, security, rollout
tests/             standard-library unittest suite (67 tests)
scripts/           validation and scenario matrix
examples/integrations/  runnable product-backend example
deploy/            systemd and Kubernetes manifests
Dockerfile         non-root container image
```
