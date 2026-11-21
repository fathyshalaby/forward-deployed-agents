# Install the meta-skill from GitHub

Repo: **https://github.com/fathyshalaby/forward-deployed-agents**

## One command

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"
```

Installs `fda-agent-builder` into `~/.claude/skills/`. Other targets:

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)" --dir "$HOME/.codex/skills"
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)" --source zip
```

From a checkout: `make install-skill`.

## Direct links

| What | URL |
|---|---|
| Repository | https://github.com/fathyshalaby/forward-deployed-agents |
| Meta-skill (raw) | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md |
| Claude upload zip | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip |
| Copy/paste prompt | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/docs/builder_prompt.md |
| Claude plugin | https://github.com/fathyshalaby/forward-deployed-agents/tree/main/plugins/fda-claude |
| Wire contract | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/docs/boilerplate.md |

## Use it

- **Claude Desktop:** upload the zip → Skills → Create skill.
- **Claude Code / Codex / Cursor:** run the one-liner, give the agent this repo + a shell.
- **ChatGPT:** paste [`builder_prompt.md`](builder_prompt.md).

```text
Use the fda-agent-builder skill to build a forward-deployed agent for my product.
```

It asks three questions and generates a bundle your customers can talk to via
Claude or ChatGPT. Runtime:

```sh
python3 -m pip install git+https://github.com/fathyshalaby/forward-deployed-agents.git
fda skill
```
