# Install the meta-skill from GitHub

Repo: **https://github.com/fathyshalaby/forward-deployed-agents**

Everything you need is public and has no runtime dependencies.

## One command

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)"
```

This installs `fda-agent-builder` into `~/.claude/skills/`. Change the location
with `--dir`, or install from the zip with `--source zip`:

```sh
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)" -- --dir "$HOME/.codex/skills"
python3 -c "$(curl -fsSL https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/scripts/install_skill.py)" -- --source zip
```

From a checkout: `make install-skill` or `python3 scripts/install_skill.py`.

## Direct links

| What | URL |
|---|---|
| Repository | https://github.com/fathyshalaby/forward-deployed-agents |
| Meta-skill (raw) | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/skills/fda-agent-builder/SKILL.md |
| Claude upload zip | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/integrations/fda-skill.zip |
| Copy/paste prompt | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/docs/builder_prompt.md |
| Claude plugin | https://github.com/fathyshalaby/forward-deployed-agents/tree/main/plugins/fda-claude |
| Boilerplate contract | https://raw.githubusercontent.com/fathyshalaby/forward-deployed-agents/main/docs/boilerplate.md |

## Use it

- **Claude Desktop:** download the zip above → Customize → Skills → `+` →
  Create skill → Upload a skill.
- **Claude Code / Codex / Cursor:** run the one-liner, or point your agent at
  the raw skill URL and give it this repo + a shell.
- **ChatGPT:** paste the raw skill or `docs/builder_prompt.md` into the chat;
  it will ask three questions and generate the bundle and product handlers.

Then say:

```text
Use the fda-agent-builder skill to build a forward-deployed agent for my product.
```

## What gets installed

Only `SKILL.md` — no code execution, no credentials, no surprises. The skill
reads [`docs/boilerplate.md`](boilerplate.md) from the repo and generates the
rest. To run the generated agent, install the runtime too:

```sh
python3 -m pip install git+https://github.com/fathyshalaby/forward-deployed-agents.git
fda --version
fda skill
```
