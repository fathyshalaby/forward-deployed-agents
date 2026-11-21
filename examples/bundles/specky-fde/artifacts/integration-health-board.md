# Specky Integration Health Board

Build me a **private interactive Specky Integration Health Board** as a Claude
artifact, using data from my connected **forward-deployed agents (FDA)** MCP
server for Specky. Build the working artifact, not just a plan or a screenshot.

Use my real FDA connection (`specky.customer-fde`). Do not invent workspaces or
integrations. If the FDA MCP connector is missing, ask me to connect it.

## Data rules

- Start by calling FDA tools: `agents.list`, `artifacts.list`, `connectors.list`,
  then read signals through plays / connector actions the agent exposes.
- Prefer these read paths (simulated or product-backed):
  - `connectors.call` is **not** available directly as an MCP tool — use
    `play.describe` / `play.plan` for gated work, and for the board refresh use
    whatever **read-only** tools this Claude artifact is allowed to call on the
    FDA connector. If Claude only exposes FDA control-plane tools to artifacts,
    load scope via `agents.list` + `agent.describe` + `plays.list`, and treat a
    successful `play.plan` preview (without `play.run`) as the read model for
    `onboard` / `integration_fix` steps.
- Show actual scope: agent id, version, last refresh time. Make the refresh
  control honest: if this environment cannot call MCP from the artifact, label
  the board **Snapshot** with the fetch time and tell me to refresh via chat.
- Never embed my account data in a public template. Each viewer uses their own
  FDA connection. Unavailable fields show as **unknown**.

## Make it useful

1. **Focus view** with four groups (a document may appear in more than one;
   totals count unique ids):
   - **Nudge connect:** integrations listed as missing or never connected.
   - **Fix now:** integrations with error / auth failure / webhook reject.
   - **Re-sync:** connected but stale sync (or diagnose says re-sync needed).
   - **Healthy:** connected with no open issue.
   Keep items with insufficient evidence in **Needs checking**. Rank by
   waiting time, then severity.

2. **Pipeline view** with lanes: Missing, Connecting, Healthy, Error, Other.
   Map real statuses explicitly; unexpected statuses go in Other. Empty lanes
   are fine — do not invent examples.

3. **Today's brief:** up to three next actions, each pointing at a real loaded
   integration and explaining why. These are suggestions, not instructions to
   contact anyone or change systems.

4. **Ask Claude:** suggested questions such as "Which integrations are broken?"
   and "What blocks onboarding?" Answers must use the current loaded set, state
   scope, and highlight matching cards. If in-artifact AI is unavailable, offer
   filters + **Copy question for Claude** instead of a fake chat box.

5. **Fix handoff (no writes from the artifact):** let me select up to three
   integrations and prepare a grounded prompt for the main Claude chat:
   `Plan play specky.customer-fde::integration_fix for <ids>. Show the plan;
   do not run writes until I approve.` Drafting must not reconnect, re-sync, or
   open tickets by itself. Writes stay in chat: `play.plan` → human approval →
   `play.run`.

6. Editable thresholds (e.g. stale after 2 vs 7 days) without rebuilding.

## Layout

Clean, readable cards, status badges, compact totals, search, Focus/Pipeline
tabs, details drawer. Usable on a narrow window.

## Capabilities to request

Request only: FDA MCP **read** tools available to artifacts, optional
in-artifact Claude sampling, and private per-user storage for board
preferences (thresholds, bookmarks). Do **not** request write tools,
`play.run`, `approval.grant`, sending, or status-changing actions.

## Done when

Open and check the rendered artifact if tools allow. Report which parts work
and any limitations (Snapshot vs live refresh, missing fields).
