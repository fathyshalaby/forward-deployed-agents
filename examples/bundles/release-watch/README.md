# Release Watch (example agent bundle)

This directory is a complete, installable agent. It demonstrates the bundle
format without touching any real system: connector results are simulated.

```sh
# from the repository root
make bundle-build BUNDLE=examples/bundles/release-watch
python3 -m fda agents install examples/bundles/dist/demo.release-watch-1.0.0.fda
python3 -m fda agents list
python3 -m fda agents skill demo.release-watch --target opencode
python3 -m fda serve
```

The MCP server then exposes both the built-in example plays and
`demo.release-watch::release_watch`. Use `play.plan`, grant the `notify`
approval, then `play.run`.

To make your own, copy this directory and edit `fda-agent.json`, `playbooks/`
and `connectors.json`, then run `python3 -m fda agents validate <dir>`.
