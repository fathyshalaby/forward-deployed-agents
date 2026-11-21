import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fda.bundle import (
    MANIFEST_FILE, BundleError, build_bundle, bundle_skill_text, export_skill,
    install_bundle, load_bundle_dir, uninstall_bundle, validate_bundle_dir,
)
from fda.cli import main as cli_main
from fda.connectors import Connector
from fda.mcp import MCPServer
from fda.runtime import load_agents_runtime
from fda.tools import tool_catalog

from .helpers import tool_result


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def make_bundle(root, identifier, connector_id="example", play_id="hello",
                write=False, skill=True):
    root = Path(root)
    manifest = {
        "schema": "fda-agent/v1",
        "id": identifier,
        "name": identifier,
        "version": "1.0.0",
        "description": "An agent used by the bundle tests.",
        "author": "tests",
        "license": "MIT",
        "tags": ["test"],
        "entry": {"playbooks": "playbooks", "connectors": "connectors.json"},
        "requires": {"fda": ">=0.2"},
    }
    if skill:
        manifest["entry"]["skill"] = "skill/SKILL.md"
    _write(root / MANIFEST_FILE, manifest)
    action = "%s.ping" % connector_id
    _write(root / "connectors.json", [{
        "id": connector_id,
        "name": "Test connector",
        "scopes": ["read", "write"],
        "actions": [action],
        "approval_required": [action] if write else [],
        "description": "Test only.",
    }])
    step = {
        "id": "ping",
        "title": "Call the custom action",
        "tool": "connectors.call",
        "connector": connector_id,
        "action": action,
        "scopes": ["read", "write"] if write else ["read"],
        "needs": ["aggregate"],
    }
    if write:
        step.update({"write": True, "purpose": "test write"})
    _write(root / "playbooks" / "play.json", {
        "id": play_id,
        "name": "Test play",
        "description": "A play used by tests.",
        "purpose": "test purpose",
        "steps": [step],
    })
    if skill:
        (root / "skill").mkdir(parents=True, exist_ok=True)
        (root / "skill" / "SKILL.md").write_text(
            "---\nname: test\n---\n# Test\n", encoding="utf-8")
    return root


def run_with_approvals(runtime, play_id):
    plan = runtime.engine.plan(play_id)
    approvals = {}
    for step in plan["steps"]:
        if step["approval_id"]:
            runtime.approvals.grant(step["approval_id"], "test-human")
            approvals[step["id"]] = step["approval_id"]
    return runtime.engine.run(play_id, approvals)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = make_bundle(self.root / "source", "acme.test-agent")
        self.store = self.root / "store"
        self.state_path = self.root / "state.db"
        env = mock.patch.dict(os.environ, {"FDA_STATE": str(self.state_path)})
        env.start()
        self.addCleanup(env.stop)

    def test_validate_report(self):
        report = validate_bundle_dir(self.source)
        self.assertTrue(report["ok"])
        self.assertEqual(report["id"], "acme.test-agent")
        self.assertEqual(report["playbook_ids"], ["acme.test-agent::hello"])
        self.assertIn("acme.test-agent::example", report["connectors"])

    def test_manifest_rejects_bad_values(self):
        import copy
        from fda.bundle import Manifest

        raw = json.loads((self.source / MANIFEST_FILE).read_text())
        bad = copy.deepcopy(raw)
        bad["schema"] = "nope"
        with self.assertRaises(BundleError) as ctx:
            Manifest.from_dict(bad)
        self.assertIn("schema must be", str(ctx.exception))

        bad = copy.deepcopy(raw)
        bad["contact"] = "alice@example.com"
        with self.assertRaises(BundleError) as ctx:
            Manifest.from_dict(bad)
        self.assertIn("unknown manifest fields", str(ctx.exception))

        bad = copy.deepcopy(raw)
        bad["description"] = "Contact ops@example.com"
        with self.assertRaises(BundleError) as ctx:
            Manifest.from_dict(bad)
        self.assertIn("secret-like text", str(ctx.exception))

    def test_undeclared_connector_is_rejected(self):
        path = self.root / "undeclared"
        make_bundle(path, "acme.undeclared")
        play = json.loads((path / "playbooks" / "play.json").read_text())
        play["steps"][0]["connector"] = "missing"
        _write(path / "playbooks" / "play.json", play)
        with self.assertRaises(BundleError) as ctx:
            load_bundle_dir(path)
        self.assertIn("undeclared connector", str(ctx.exception))

    def test_namespacing_and_custom_action_runs(self):
        bundle = load_bundle_dir(self.source)
        self.assertEqual(list(bundle.playbooks), ["acme.test-agent::hello"])
        step = bundle.playbooks["acme.test-agent::hello"].steps[0]
        self.assertEqual(step.connector, "acme.test-agent::example")
        self.assertEqual(step.action, "acme.test-agent::example.ping")

        install_bundle(build_bundle(self.source, self.root / "one.fda"), self.store)
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        run = runtime.engine.run("acme.test-agent::hello")
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["results"][0]["result"]["mode"], "simulated")
        self.assertTrue(run["results"][0]["result"]["ok"])

    def test_write_step_needs_approval_after_namespacing(self):
        source = make_bundle(self.root / "write-agent", "acme.write-agent",
                             write=True)
        install_bundle(build_bundle(source, self.root / "write.fda"), self.store)
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        play_id = "acme.write-agent::hello"
        denied = runtime.engine.run(play_id)
        self.assertEqual(denied["status"], "denied")
        completed = run_with_approvals(runtime, play_id)
        self.assertEqual(completed["status"], "complete")

    def test_real_adapter_handler_is_used(self):
        source = make_bundle(self.root / "adapter-agent", "acme.adapter-agent",
                             write=True)
        install_bundle(build_bundle(source, self.root / "adapter.fda"), self.store)
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        runtime.connectors.register_handler(
            "acme.adapter-agent::example.ping", lambda ctx: {"posted": True})
        run = run_with_approvals(runtime, "acme.adapter-agent::hello")
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["results"][0]["result"]["mode"], "adapter")
        self.assertTrue(run["results"][0]["result"]["posted"])

    def test_build_install_roundtrip_and_uninstall(self):
        archive = build_bundle(self.source, self.root / "dist" / "agent.fda")
        self.assertTrue(archive.exists())
        bundle = install_bundle(archive, self.store)
        self.assertEqual(bundle.manifest.id, "acme.test-agent")
        with self.assertRaises(BundleError):
            install_bundle(archive, self.store)
        install_bundle(archive, self.store, force=True)
        self.assertTrue(uninstall_bundle("acme.test-agent", self.store))
        self.assertFalse(uninstall_bundle("acme.test-agent", self.store))

    def test_install_rejects_traversal_and_symlinks(self):
        archive = self.root / "evil.fda"
        with zipfile.ZipFile(archive, "w") as zipf:
            zipf.writestr(MANIFEST_FILE, json.dumps({
                "schema": "fda-agent/v1", "id": "acme.evil", "name": "Evil",
                "version": "1.0.0", "description": "nope",
                "entry": {"playbooks": "playbooks"},
            }))
            zipf.writestr("../escape.json", "{}")
        with self.assertRaises(BundleError):
            install_bundle(archive, self.store)
        self.assertFalse((self.root / "escape.json").exists())

        archive = self.root / "symlink.fda"
        info = zipfile.ZipInfo("fda-agent.json")
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as zipf:
            zipf.writestr(info, "{}")
        with self.assertRaises(BundleError):
            install_bundle(archive, self.store)

    def test_two_bundles_with_same_connector_id_do_not_collide(self):
        for identifier in ("acme.one", "acme.two"):
            source = make_bundle(self.root / identifier, identifier,
                                 connector_id="chat", play_id="notify")
            install_bundle(build_bundle(source, self.root / (identifier + ".fda")),
                           self.store)
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        self.assertEqual(set(runtime.playbooks),
                         {"acme.one::notify", "acme.two::notify"})
        self.assertEqual(len(runtime.connectors.list_public()), 2)
        for play_id in ("acme.one::notify", "acme.two::notify"):
            self.assertEqual(runtime.engine.run(play_id)["status"], "complete")

    def test_mcp_tools_for_bundles(self):
        source = make_bundle(self.root / "mcp-agent", "acme.mcp-agent")
        install_bundle(build_bundle(source, self.root / "mcp.fda"), self.store)
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        server = MCPServer(runtime)
        names = [tool["name"] for tool in tool_catalog()]
        self.assertIn("agents.list", names)

        payload = tool_result(runtime, "agents.list")
        self.assertEqual([row["id"] for row in payload["agents"]], ["acme.mcp-agent"])
        payload = tool_result(runtime, "agent.describe",
                              {"agent_id": "acme.mcp-agent"})
        self.assertEqual(payload["version"], "1.0.0")
        self.assertNotIn("source", payload)
        payload = tool_result(runtime, "agent.skill",
                              {"agent_id": "acme.mcp-agent"})
        self.assertIn("# Test", payload["skill"])
        payload = tool_result(runtime, "agent.skill", {
            "agent_id": "acme.mcp-agent", "prefer_custom": False,
        })
        self.assertIn("acme.mcp-agent::hello", payload["skill"])
        error = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "agent.skill", "arguments": {"agent_id": "missing"}},
        })
        self.assertTrue(error["result"]["isError"])

    def test_skill_export_prefers_bundled_file_then_generates(self):
        bundle = load_bundle_dir(self.source)
        self.assertIn("# Test", bundle_skill_text(bundle))
        self.assertNotIn("# Test", bundle_skill_text(bundle, prefer_custom=False))
        destination = export_skill(bundle, self.root / "export" / "SKILL.md",
                                   prefer_custom=False)
        text = destination.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("acme.test-agent::hello", text)
        self.assertIn("acme.test-agent::example", text)

    def test_cli_lifecycle(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli_main(["agents", "init", str(self.root / "cli-agent"),
                                       "--id", "acme.cli-agent", "--name", "CLI Agent",
                                       "--description", "Created by a test"]), 0)
            self.assertEqual(cli_main(["agents", "validate",
                                       str(self.root / "cli-agent")]), 0)
            self.assertEqual(cli_main(["agents", "build",
                                       str(self.root / "cli-agent"),
                                       "-o", str(self.root / "cli.fda")]), 0)
            self.assertEqual(cli_main(["agents", "install", str(self.root / "cli.fda"),
                                       "--store", str(self.store),
                                       "--state", str(self.state_path)]), 0)
            self.assertEqual(cli_main(["agents", "list", "--store", str(self.store)]), 0)
            self.assertEqual(cli_main(["agents", "describe", "acme.cli-agent",
                                       "--store", str(self.store)]), 0)
            self.assertEqual(cli_main(["agents", "skill", "acme.cli-agent",
                                       "--store", str(self.store),
                                       "--generated", "-o", str(self.root / "out")]), 0)
        self.assertTrue((self.root / "out" / "acme-cli-agent.md").exists())
        self.assertIn("acme.cli-agent", output.getvalue())

    def test_installed_wheel_without_examples_still_serves_bundles(self):
        from unittest import mock
        import os

        source = make_bundle(self.root / "wheel-agent", "acme.wheel-agent")
        install_bundle(build_bundle(source, self.root / "wheel.fda"), self.store)
        with mock.patch.dict(os.environ, {"FDA_STATE": str(self.state_path)},
                             clear=True), \
                mock.patch("fda.runtime.examples_present", return_value=False):
            runtime = load_agents_runtime(store=self.store)
            self.assertEqual(list(runtime.playbooks), ["acme.wheel-agent::hello"])
            self.assertEqual(runtime.engine.run("acme.wheel-agent::hello")["status"],
                             "complete")

    def test_duplicate_connector_registration_is_last_write_wins(self):
        runtime = load_agents_runtime(store=self.store, include_examples=False)
        runtime.connectors.register(Connector(
            id="example", name="replacement", scopes=["read"], actions=[]))
        self.assertEqual(runtime.connectors.get("example").name, "replacement")


if __name__ == "__main__":
    unittest.main()
