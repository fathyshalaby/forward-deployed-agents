"""Deployment-grade controls: durable state, approvals, trust and ops."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from fda.approval_ui import serve as serve_approvals
from fda.bundle import MANIFEST_FILE, BundleError, build_bundle, install_bundle
from fda.cli import main as cli_main
from fda.mcp import MCPServer
from fda.runtime import load_agents_runtime
from fda.security import (
    Keyring, Registry, Signer, Verifier, content_hash, generate_key,
)
from fda.store import StateStore

from .test_bundles import make_bundle


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_path = self.root / "state.db"
        self.audit_path = self.root / "audit.jsonl"
        self.store = self.root / "agents"
        self.env = mock.patch.dict(
            os.environ, {"FDA_STATE": str(self.state_path)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def runtime(self, **kwargs):
        options = {
            "store": self.store,
            "include_examples": True,
            "persist_audit": True,
            "audit_path": self.audit_path,
            "state_path": self.state_path,
        }
        options.update(kwargs)
        return load_agents_runtime(**options)

    def test_durable_runs_approvals_and_audit_survive_restart(self):
        first = self.runtime()
        plan = first.engine.plan("onboarding")
        approvals = {}
        for step in plan["steps"]:
            if step["approval_id"]:
                first.approvals.grant(step["approval_id"], "ops-human")
                approvals[step["id"]] = step["approval_id"]
        run = first.engine.run("onboarding", approvals,
                               {"tenant": "acme", "actor": "alice"})
        self.assertEqual(run["status"], "complete")

        second = self.runtime()
        self.assertEqual(second.engine.status(run["run_id"])["status"], "complete")
        explained = second.audit.explain()
        self.assertGreater(explained["entries"], 0)
        self.assertTrue(all("tenant" in row for row in explained["timeline"]))
        self.assertTrue(second.state.audit_verify()["ok"])

    def test_external_mode_forbids_model_grant(self):
        runtime = self.runtime(approval_mode="external")
        plan = runtime.engine.plan("onboarding")
        approval_id = next(step["approval_id"] for step in plan["steps"]
                           if step["approval_id"])
        response = MCPServer(runtime).handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "approval.grant", "arguments": {
                "approval_id": approval_id, "approver": "model"}},
        })
        self.assertTrue(response["result"]["isError"])
        self.assertIn("out-of-band", response["result"]["content"][0]["text"])
        self.assertEqual(runtime.state.approval_get(approval_id)["status"], "pending")

        ok, status = runtime.state.approval_decide(approval_id, "grant", "human")
        self.assertTrue(ok)
        self.assertEqual(status, "granted")

    def test_kill_switch_stops_runs_and_can_be_resumed(self):
        state = StateStore(self.state_path)
        state.kill_set("*", True, "security incident")
        runtime = self.runtime()
        denied = runtime.engine.run("access_review")
        self.assertEqual(denied["status"], "denied")
        self.assertIn("kill switch", denied["results"][0]["error"])
        state.kill_set("*", False, "")
        self.assertEqual(runtime.engine.run("access_review")["status"], "complete")

    def test_approval_is_bound_to_actor_and_context(self):
        runtime = self.runtime()
        context = {"tenant": "acme", "actor": "alice", "ticket": "INC-1"}
        plan = runtime.engine.plan("onboarding", context)
        approvals = {}
        for step in plan["steps"]:
            if step["approval_id"]:
                runtime.approvals.grant(step["approval_id"], "human")
                approvals[step["id"]] = step["approval_id"]
        denied = runtime.engine.run("onboarding", approvals,
                                    {"tenant": "acme", "actor": "bob",
                                     "ticket": "INC-1"})
        self.assertEqual(denied["status"], "denied")
        self.assertIn("actor does not match", denied["results"][1]["error"])

    def test_audit_hash_chain_detects_tampering(self):
        state = StateStore(self.state_path)
        state.audit_append({"ts": "2026-01-01T00:00:00Z", "tool": "test",
                            "decision": "allow", "purpose": "original"})
        self.assertTrue(state.audit_verify()["ok"])
        with sqlite3.connect(str(self.state_path)) as conn:
            conn.execute("UPDATE audit SET payload=REPLACE(payload,'original','edited')")
        result = state.audit_verify()
        self.assertFalse(result["ok"])
        self.assertEqual(result["broken_seq"], [1])

    def test_signature_trust_registry_and_revocation(self):
        key = generate_key("acme", "Acme Inc", self.root / "acme.key")
        trust = self.root / "trust.json"
        keyring = Keyring(trust)
        keyring.add(key)
        verifier = Verifier(keyring, require=True)

        source = make_bundle(self.root / "source", "acme.signed")
        archive = build_bundle(source, self.root / "signed.fda",
                               signer=Signer(key["key_id"], key["secret"]))
        installed = install_bundle(archive, self.store, verifier=verifier,
                                   state=StateStore(self.state_path))
        self.assertTrue(installed.manifest.id)

        unsigned = build_bundle(source, self.root / "unsigned.fda")
        with self.assertRaises(BundleError):
            install_bundle(unsigned, self.root / "other", verifier=verifier)

        other_key = generate_key("evil", "No one", self.root / "evil.key")
        foreign = build_bundle(source, self.root / "foreign.fda",
                               signer=Signer(other_key["key_id"],
                                             other_key["secret"]))
        with self.assertRaises(BundleError):
            install_bundle(foreign, self.root / "other", verifier=verifier)

        registry = Registry(self.root / "registry")
        registry.init()
        entry = registry.publish(archive, verifier=verifier, key_id="acme")
        self.assertEqual(entry["id"], "acme.signed")
        install_bundle(archive, self.root / "registry-store",
                       registry=registry)
        registry.revoke("acme.signed", "1.0.0", "compromised")
        with self.assertRaises(BundleError):
            install_bundle(archive, self.root / "registry-store",
                           registry=registry, force=True)

    def test_pin_detects_changed_bundle_and_ops_revoke_skips_it(self):
        source = make_bundle(self.root / "source", "acme.pinned")
        archive = build_bundle(source, self.root / "pinned.fda")
        install_bundle(archive, self.store, state=StateStore(self.state_path),
                       pin=True)
        self.runtime()  # pinned bundle loads cleanly

        playbook = self.store / "acme.pinned" / "playbooks" / "play.json"
        raw = json.loads(playbook.read_text())
        raw["purpose"] = "changed after review"
        playbook.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.runtime()

        StateStore(self.state_path).revoke("acme.pinned", "*", "bad bundle")
        runtime = self.runtime()
        self.assertNotIn("acme.pinned::hello", runtime.playbooks)

    def test_cli_ops_and_approvals(self):
        state = StateStore(self.state_path)
        state.approval_save({
            "id": "a-test", "action": "play.run.test.step",
            "reason": "test", "needs": ["metadata"], "purpose": "test",
            "status": "pending",
        })
        self.assertEqual(cli_main(["approvals", "list", "--state",
                                   str(self.state_path)]), 0)
        self.assertEqual(cli_main(["approvals", "grant", "a-test", "--approver",
                                   "human", "--state", str(self.state_path)]), 0)
        self.assertEqual(state.approval_get("a-test")["status"], "granted")

        self.assertEqual(cli_main(["ops", "pause", "--scope", "acme",
                                   "--reason", "maintenance", "--state",
                                   str(self.state_path)]), 0)
        self.assertTrue(state.kill_check("acme")["paused"])
        self.assertEqual(cli_main(["ops", "status", "--state",
                                   str(self.state_path)]), 0)
        self.assertEqual(cli_main(["ops", "resume", "--scope", "acme",
                                   "--state", str(self.state_path)]), 0)
        self.assertFalse(state.kill_check("acme")["paused"])
        self.assertEqual(cli_main(["ops", "audit-verify", "--state",
                                   str(self.state_path)]), 0)

    def test_approval_ui_requires_token_and_records_decision(self):
        state = StateStore(self.state_path)
        state.approval_save({
            "id": "a-ui", "action": "play.run.test.step",
            "reason": "needs a human", "needs": ["metadata"],
            "purpose": "test", "status": "pending",
        })
        server = serve_approvals(self.state_path, "secret-token", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        base = "http://127.0.0.1:%d" % port

        with urllib.request.urlopen(base + "/health") as response:
            self.assertTrue(json.loads(response.read())["ok"])

        request = urllib.request.Request(base + "/approvals")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 401)

        request = urllib.request.Request(
            base + "/approvals", headers={"X-FDA-Token": "secret-token"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(len(json.loads(response.read())["approvals"]), 1)

        body = json.dumps({"approver": "ui-human"}).encode()
        request = urllib.request.Request(
            base + "/approvals/a-ui/grant", data=body,
            headers={"X-FDA-Token": "secret-token", "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.loads(response.read())["status"], "granted")
        self.assertEqual(state.approval_get("a-ui")["status"], "granted")


if __name__ == "__main__":
    unittest.main()
