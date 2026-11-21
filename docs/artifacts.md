# Claude artifacts as an FDE tool

Your customers talk to the FDA through Claude or ChatGPT. **Artifacts** are the
custom UI layer on top: interactive boards that call your FDA MCP **read**
tools, the same pattern as connector-backed Claude artifacts (pipeline boards,
health dashboards, etc.).

## Who owns what

| Layer | Who touches it | Evolves how |
|---|---|---|
| FDA runtime + approvals + audit | Product / ops | Rare; versioned deploys |
| Agent bundle (plays, connectors) | Product via the meta-skill | Rebuild + reinstall |
| Claude artifact recipes | Shipped in `artifacts/*.md` | Edit recipe; customer rebuilds UI in Claude |
| Customer's pinned artifact | Customer | Iterates in Claude; their own MCP connection |

Customers never touch your infra. The skill and recipes evolve; the control
plane stays put.

## Hard rule (Claude)

Artifacts may use connector tools that do **not** need per-action approval.
So: **read from the artifact, write in chat**.

```
artifact refresh  -> FDA read tools / play.describe / play.plan preview
customer wants a fix -> handoff prompt in chat
                     -> play.plan -> human grant -> play.run
```

## Ship a recipe in a bundle

```
agents/<id>/
  artifacts/
    integration-health-board.md   # paste/build prompt for Claude
```

After install, MCP exposes:

- `artifacts.list` — recipes on installed agents
- `artifacts.get` — full recipe markdown

The meta-skill tells the builder to add at least one recipe for the customer's
recurring UI job. Flagship example:
[`examples/bundles/specky-fde/artifacts/`](../examples/bundles/specky-fde/artifacts/).

## Customer flow

1. Product deploys FDA + installs the Specky (or their) agent.
2. Customer connects Claude Desktop / ChatGPT to `fda serve` (MCP).
3. Customer: "Build the Specky Integration Health Board from `artifacts.get`."
4. Claude builds a private artifact on their connection; they pin it.
5. Fixes still go through approved plays in the conversation.
