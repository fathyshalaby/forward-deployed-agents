# Connect an installed agent to your AI

Install the bundle first (see [agent_bundles.md](agent_bundles.md)). The server
is a standard MCP stdio server, so any MCP client can use it. No API key is
needed by the framework itself: connector credentials stay inside your boundary
and are never shown to the agent.

## 1. Install and check

```sh
python3 -m fda agents install path/to/agent.fda
python3 -m fda agents list
python3 -m fda serve          # leave this running, or let the client start it
```

If you installed with `pip install .`, replace `python3 -m fda` with `fda` in the
examples below.

## 2. Point your client at the server

### OpenCode / generic MCP clients

Add to your client's MCP config (for OpenCode, `opencode.json`):

```json
{
  "mcp": {
    "fda": {
      "type": "local",
      "command": ["python3", "-m", "fda", "serve"],
      "enabled": true
    }
  }
}
```

If you run from a checkout, set the working directory to the repository root or
use an absolute path with `PYTHONPATH=src`.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fda": {
      "command": "python3",
      "args": ["-m", "fda", "serve"],
      "env": {"FDA_AGENTS": "/absolute/path/to/.fda/agents"}
    }
  }
}
```

Restart the client. Ask it to call `agents.list`; it should report your installed
agents.

## 3. Give the client a skill (optional)

MCP gives the model tools. A skill gives it the operating rules for a particular
agent. Write the skill into the client's skills directory:

```sh
python3 -m fda agents skill acme.my-agent --target opencode
python3 -m fda agents skill acme.my-agent --target claude
```

Or export it anywhere and attach it manually:

```sh
python3 -m fda agents skill acme.my-agent -o ~/skills/my-agent/SKILL.md
```

The generated skill contains the namespaced playbook ids and connectors, and
repeats the non-negotiables: plan first, ask a human for approval, fail closed,
and keep content out of the audit trail.

## 4. A safe first session

Ask your AI, in plain language:

1. "List the installed agents and the connectors I granted."
2. "Describe `acme.my-agent::my_play`."
3. "Plan that play and show me what needs approval."
4. "I approve step X" — grant it out-of-band (`fda approvals grant <id>
   --approver you`, or the approval UI) before the model calls `play.run`.
5. "Explain the run from the audit trail."

Watch for a model that skips `play.plan`, broadens scopes, or claims success
without a run id. Treat those as stop conditions.

## Troubleshooting

| Symptom | Check |
|---|---|
| no agents listed | `python3 -m fda agents list`; verify `FDA_AGENTS` path |
| tool errors on custom actions | connector descriptor must declare the action and scopes |
| approval denied | approval is single-use and bound to exact action + purpose |
| content step denied | needs an explicit purpose and a purpose-bound approval |
| client cannot start server | start `python3 -m fda serve` manually and check stderr |
| built-in examples missing | expected after `pip install .`; installed bundles still work, or set `FDA_PLAYBOOKS`/`FDA_CONNECTORS` |
| `approval.grant` fails | expected with `FDA_APPROVAL_MODE=external`; grant in the approval UI or CLI |

MCP protocol traffic is one JSON message per line on stdout; diagnostics go to
stderr. That is why the stdio server composes cleanly with clients.
