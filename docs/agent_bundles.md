# Agent bundles: build, package and share an agent

A **bundle** is the thing you hand to someone else. It is one versioned folder
(or one `.fda` archive) containing the playbooks, connector descriptors and
optional AI skill for an agent. The person receiving it does not edit Python or
set environment variables: they install it, point their AI client at the server
and run it.

```
builder                         user
-------                         ----
fda agents init                 fda agents install agent.fda
edit playbooks + descriptors -> fda agents list
fda agents validate             fda agents skill <id> --target opencode
fda agents build                fda serve  (MCP stdio)
```

## Quickest path

```sh
python3 -m fda agents init ./my-agent \
  --id acme.my-agent --name "My Agent" --description "What it does"
python3 -m fda agents validate ./my-agent
python3 -m fda agents build ./my-agent -o dist/acme.my-agent-0.1.0.fda
python3 -m fda agents install dist/acme.my-agent-0.1.0.fda
python3 -m fda agents list
```

The scaffold contains a working example play, a harmless connector descriptor
and a generated `SKILL.md`. Replace those with your own.

## Folder layout

```
my-agent/
  fda-agent.json          required: manifest
  playbooks/              required: one JSON playbook per file
    my_play.json
  connectors.json         optional: descriptors the playbooks may use
  skill/SKILL.md          optional: AI skill shipped with the agent
  README.md               optional
```

Only `.json`, `.md`, `.txt`, `.yaml` and `.yml` files are packaged. No Python,
no executables, no symlinks. Credentials and endpoints do not belong in a
bundle: connectors are capabilities the user grants at runtime.

## Manifest (`fda-agent.json`)

```json
{
  "schema": "fda-agent/v1",
  "id": "acme.my-agent",
  "name": "My Agent",
  "version": "0.1.0",
  "description": "One sentence on what this agent does for the user.",
  "author": "Acme",
  "license": "MIT",
  "tags": ["custom"],
  "entry": {
    "playbooks": "playbooks",
    "connectors": "connectors.json",
    "skill": "skill/SKILL.md"
  },
  "requires": { "fda": ">=0.2" },
  "capabilities": ["tickets.search"]
}
```

| Field | Rule |
|---|---|
| `schema` | must be `fda-agent/v1` |
| `id` | lowercase slug, 2–64 chars: letters, digits, `.`, `_`, `-` |
| `version` | `MAJOR.MINOR.PATCH`, optional suffix |
| `description` | required, at most 300 characters |
| `entry.playbooks` | directory of `*.json`, default `playbooks` |
| `entry.connectors` | JSON descriptor file or object with `connectors` list; omit if unused |
| `entry.skill` | optional markdown skill path |
| `requires.fda` | optional version hint; currently advisory |

Unknown fields are rejected. Secret-like values (emails, `ghp_...` tokens,
bearer headers) in the manifest are rejected too.

## Namespacing

Every playbook id, connector id and connector action is prefixed at load time:

```
my_play            ->  acme.my-agent::my_play
tickets            ->  acme.my-agent::tickets
tickets.create     ->  acme.my-agent::tickets.create
```

That means two independently authored agents can both declare a `chat`
connector. The rewrite is automatic; write local names in your bundle files.
`play.describe` and `play.plan` show the final namespaced ids.

## Connector descriptors

Descriptors declare only id, name, scopes, actions, approval requirements and a
description. See [privacy_model.md](privacy_model.md) for the scope rules.

```json
[
  {
    "id": "deploy",
    "name": "Deploy pipeline",
    "scopes": ["read"],
    "actions": ["deploy.status"],
    "approval_required": [],
    "description": "Aggregate signals; no payloads."
  }
]
```

`validate` fails if a playbook step names a connector the bundle did not
declare. Unknown actions, missing scopes and undeclared connectors fail closed
at run time in the engine, not in the prompt.

### Custom actions and simulated mode

The built-in demo has a fixed table of simulated results. A bundle's custom
actions (for example `deploy.status`) are not in that table. The server handles
this with a generic, non-sensitive simulated result such as
`{"ok": true, "mode": "simulated"}`. The descriptor still gates which actions
can run, so nothing new is executable just because it was typed in a playbook.

Real adapters are bound by the operator, never by the bundle:

```python
runtime.connectors.register_handler(
    "acme.my-agent::deploy.status",
    lambda ctx: {"deploy_ok": True, "error_rate": 0.01},
)
```

Bundles are declarative and cannot ship Python. See the "How to build it for
real" section of [deep_dive.md](deep_dive.md) for container isolation, hashed
tool definitions and scoped tokens.

## Validation, packaging and install

```sh
python3 -m fda agents validate ./my-agent
python3 -m fda agents build ./my-agent -o dist/my-agent.fda
python3 -m fda agents install dist/my-agent.fda [--force]
python3 -m fda agents list [--json]
python3 -m fda agents describe acme.my-agent
python3 -m fda agents uninstall acme.my-agent
```

The `.fda` archive is a zip with the manifest at its root. Install performs
validation **before** writing to the store and rejects absolute paths,
`..` traversal, backslashes, symlinks, oversized files and unsupported file
types. The default store is `~/.fda/agents`; set `FDA_AGENTS` to change it.
Reinstalling the same id requires `--force`.

## Exporting the skill

Each bundle can ship its own `skill/SKILL.md`. If it does not, one is generated
from the manifest with the namespaced play and connector ids.

```sh
python3 -m fda agents skill acme.my-agent                 # print to stdout
python3 -m fda agents skill acme.my-agent -o SKILL.md     # write a file
python3 -m fda agents skill acme.my-agent --target opencode
python3 -m fda agents skill acme.my-agent --target claude
python3 -m fda agents skill acme.my-agent --generated     # ignore bundled skill
```

`--target opencode` writes to `.opencode/skills/<name>/SKILL.md`;
`--target claude` writes to `.claude/skills/<name>/SKILL.md`. An AI client can
also fetch the same text at run time through the `agent.skill` MCP tool.

## Serving multiple agents

```sh
python3 -m fda serve                     # examples + every installed bundle
python3 -m fda serve --no-examples       # only installed bundles
python3 -m fda serve --store /path/to/store
FDA_AGENTS=/path/to/store python3 -m fda serve
```

The MCP surface gains `agents.list`, `agent.describe` and `agent.skill`; the
existing ten tools are unchanged. See [mcp_tools.md](mcp_tools.md) and
[connect_an_ai.md](connect_an_ai.md).

## Review checklist before sharing

- [ ] `agents validate` passes with no warnings you cannot explain.
- [ ] Every write step has a purpose and a human approval gate.
- [ ] No step asks for `content` unless the user made a separate decision.
- [ ] Descriptors expose no credentials, hosts or raw payload shapes.
- [ ] The skill tells the agent to plan, ask for approval and fail closed.
- [ ] You ran the play once with approvals and once without, and read
      `audit.explain` both times.
- [ ] The archive checksum is published with the file.
