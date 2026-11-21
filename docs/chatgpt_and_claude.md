# Connect FDA to ChatGPT and Claude

This is the practical bridge from "we have an agent framework" to "people can
use the agent from the AI they already have". The same runtime is exposed two
ways:

| Client | Transport | What you add |
|---|---|---|
| ChatGPT (web) | remote MCP over **SSE / streaming HTTP** | a custom MCP server plugin |
| Claude Desktop | local **stdio** MCP + uploaded skill | one config entry + one skill |
| Claude Code / Cowork | stdio MCP + skills, or a bundled **plugin** | `.mcp.json` + skill, or `plugins/fda-claude/` |
| claude.ai (web) | remote MCP connector by URL | HTTPS URL (+ header if needed) |

MCP gives the model tools. The **skill** gives it the operating rules: plan
first, a human approves, never self-grant, fail closed. Use both.

> 2026 note: custom GPT **Actions** are being retired (Dec 11, 2026). Do not
> build a new GPT Action around the JSON API — use a custom MCP server plugin.
> Full custom MCP in ChatGPT is available on Business / Enterprise / Edu; Pro
> is read/fetch limited. See OpenAI's "Add custom MCP server" docs.

## 0. Prepare once

Install the agent bundle and decide where durable state lives:

```sh
python3 -m pip install .
fda agents install dist/acme.my-agent-1.0.0.fda
fda agents list

export FDA_STATE=/var/lib/fda/state.db          # or ~/.fda/state.db
export FDA_APPROVAL_MODE=external               # the model cannot self-approve
fda doctor
```

## 1. Remote MCP server (for ChatGPT, claude.ai, remote Claude)

Start the HTTP/SSE transport. It speaks the same 15 MCP tools as the stdio
server.

```sh
fda serve --transport http --host 0.0.0.0 --port 8000 \
  --token "$FDA_MCP_TOKEN" --no-examples
curl https://agent.example.com/health   # {"ok":true,"transport":"http/sse",...}
```

Put TLS in front of it (reverse proxy, Secure MCP Tunnel, or an OAuth proxy).
`GET /mcp` is the SSE stream; `POST /mcp` accepts JSON-RPC (JSON or SSE reply).

### ChatGPT

1. In ChatGPT web, open **Plugins → `+` → Add custom MCP server**.
2. Name: `Forward Deployed Agents`. Description: "Run governed agent playbooks
   with human approvals and audit."
3. Connection → Server URL: `https://agent.example.com/mcp` (SSE or streaming
   HTTP). Choose the matching protocol.
4. Authentication: use **OAuth** in production, or **no authentication** only
   if the URL is private/tunnelled. Clients that can send headers may use the
   bearer token (`Authorization: Bearer $FDA_MCP_TOKEN`); ChatGPT's MCP form
   does not expose a generic API-key field.
5. Accept the risk warning → **Create as a plugin** → install it.
6. In a conversation, type `@` and select the plugin, then ask:

   > Use the FDA plugin's `agents.list` tool, then `plays.list`. Plan
   > `acme.my-agent::my_play` and show me the approval ids. Do not call
   > `play.run` until I grant one out-of-band.

The server's `initialize` response includes instructions and every tool carries
MCP annotations, so read-only tools (`plays.list`, `play.plan`, `ops.status`)
are recognised as reads while `play.run` / `approval.grant` ask for confirmation.

### claude.ai / remote Claude connector

Add a custom connector with URL `https://agent.example.com/mcp`. If your plan
supports request headers, add `Authorization: Bearer $FDA_MCP_TOKEN`. Then
mention the connector in a chat.

## 2. Claude Desktop (local, stdio)

Copy the example config and use **absolute paths** — Claude Desktop does not
inherit your shell PATH:

```sh
cp integrations/claude_desktop_config.example.json \
   "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
# edit /usr/local/bin/fda and the FDA_STATE / FDA_AGENTS paths
```

Quit and reopen Claude Desktop. Test with "call fda `agents.list`". Logs are in
`~/Library/Logs/Claude` if the server does not appear.

Upload the meta-skill once: **Customize → Skills → `+` → Create skill → Upload a
skill** and select [`integrations/fda-skill.zip`](../integrations/fda-skill.zip).
It contains one skill, `fda-agent-builder`, which reads our boilerplate and
builds an agent for any product/language. You can also paste the prompt from
[builder_prompt.md](builder_prompt.md) into Claude Code, Codex or any chat with
a shell.

## 3. Claude Code / Cowork

Project-scoped setup (commit these if you want the team to share it):

```sh
cp integrations/claude_code.mcp.example.json .mcp.json
mkdir -p .claude/skills
cp -r plugins/fda-claude/skills/fda-agent-builder \
      .claude/skills/
```

Or install the bundled plugin from [`plugins/fda-claude/`](../plugins/fda-claude/)
through Claude's plugin manager. It contains `.claude-plugin/plugin.json`,
`.mcp.json` and the skill, so MCP access and operating rules arrive together.
For an org-wide rollout, place that directory under `org-plugins/` and bump
`version.json` when you want clients to re-sync.

## 4. Verify the whole loop

Ask the client, in this order:

1. "List installed agents and connectors."
2. "Describe the play `acme.my-agent::my_play`."
3. "Plan it and show me what needs approval." (a human grants the id via
   `fda approvals grant <id> --approver alice`)
4. "Check `approval.status` then run with that approval."
5. "Explain the run from the audit trail."

Stop conditions: the model invents an approval id, calls `play.run` before a
grant, widens scopes, or claims success without a run id. `ops.status` shows the
kill switch and audit-chain health.

## Troubleshooting

| Symptom | Fix |
|---|---|
| ChatGPT cannot add the server | must be HTTPS; check SSE/streaming HTTP choice; full MCP needs Business+ |
| Claude Desktop shows no tools | absolute `command` path; valid JSON; full app restart |
| `approval.grant` fails | expected in `external` mode — a human uses the approval UI/CLI |
| empty `agents.list` | `fda agents list`; check `FDA_AGENTS` in the server process |
| `kill switch active` | an operator paused the tenant; see `fda ops status` |
| content step denied | needs explicit purpose + purpose-bound approval |
