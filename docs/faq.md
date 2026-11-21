# FAQ

## Is this a hosted service?

No. The runtime runs inside your boundary — a process, container, VM or
Kubernetes pod that you control. Connector credentials never enter the agent
bundle or the model context; they are read only by your operator-side handlers.

## Does it need third-party packages?

No. The runtime, MCP server, HTTP adapters, signing, registry and state store
use only the Python standard library. SQLite is the sole state backend.

## Can the AI grant its own approvals?

Not in production. Set `FDA_APPROVAL_MODE=external`: the MCP `approval.grant`
tool always fails, and a human grants via `fda approvals grant` or the approval
UI. Approvals are single-use and bound to action, purpose, data classes, actor,
playbook hash and argument hash.

## Is signing public-key cryptography?

No. It is HMAC-SHA256 with an explicit local trust store. That gives tamper
detection and explicit publisher identity, not public-key non-repudiation. See
[security.md](security.md) for the full trust model.

## Can I use this without ChatGPT or Claude?

Yes. `fda.sdk.Client` embeds the runtime in a Python product, and `fda api serve`
exposes the same capabilities as a JSON HTTP API for any other stack. The MCP
server is just another adapter.

## Where does state live?

One SQLite file at `FDA_STATE` (default `~/.fda/state.db`). It holds runs,
approvals, the hash-chained audit trail, revocations, pins and the kill switch.
Back it up. `fda ops audit-verify` detects edits; ship audit entries to a
write-only sink for real tamper evidence.

## What is a "bundle"?

A versioned `fda-agent/v1` zip containing declarative manifests, JSON playbooks
and a skill. It cannot contain executable Python, credentials, symlinks, path
traversal or oversized files. Ids are namespaced (`<bundle id>::<play id>`) so
bundles cannot collide.

## How do I roll out a fix?

Build a new version, sign and publish it, then install with `--verify
--registry-check --pin`. Revoke the old version with `fda ops revoke` or
`fda registry revoke`. In an emergency, `fda ops pause --scope <tenant>` stops
all runs before any connector is called.

## Does it write customer content to the audit?

No. Free text is stored as a hash. `audit.explain` shows what happened — which
tool, scopes, data classes, approvals and denials — without payloads.

## Can I plug in my real APIs?

Yes. Register a connector descriptor in the bundle, then bind an operator-side
callable with `client.register_handler(action, fn)` or
`ConnectorRegistry.register_handler`. The handler receives only
`{connector, action, scopes, needs}` and returns a small JSON dict.

## How do I onboard a new product quickly?

Run `fda skill` and paste the output into your AI with a product description.
It asks three questions, builds and wires the agent, deploys it and verifies the
run. The [tutorial](tutorial.md) walks through the same steps manually.

## What is still a prototype?

There is no OAuth broker or secret store in the repository (bring your own),
the audit chain needs a write-only sink for tamper evidence, and runs are
durable records rather than a full workflow engine with retries/queues/cron.
Connections to real systems are only as good as the handlers you register.
