"""Claude artifact recipes shipped inside agent bundles."""
import tempfile
import unittest
from pathlib import Path

from fda.bundle import build_bundle, install_bundle, list_artifact_recipes, load_bundle_dir
from fda.runtime import load_agents_runtime
from fda.tools import call_tool

from .helpers import tool_result

ROOT = Path(__file__).resolve().parents[1]
SPECKY = ROOT / "examples" / "bundles" / "specky-fde"


class ArtifactRecipeTests(unittest.TestCase):
    def test_specky_ships_integration_health_board(self):
        bundle = load_bundle_dir(SPECKY)
        items = list_artifact_recipes(bundle)
        self.assertEqual([i["id"] for i in items], ["integration-health-board"])
        self.assertIn("Integration Health", items[0]["title"])

    def test_mcp_artifacts_list_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_bundle(SPECKY, Path(tmp) / "specky.fda")
            store = Path(tmp) / "agents"
            install_bundle(archive, store=store)
            runtime = load_agents_runtime(store=store, include_examples=False)
            listed = tool_result(runtime, "artifacts.list")
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["artifacts"][0]["id"], "integration-health-board")
            got = call_tool(runtime, "artifacts.get", {
                "agent_id": "specky.customer-fde",
                "artifact_id": "integration-health-board",
            })
            self.assertIn("Build me a **private interactive Specky", got["recipe"])
            self.assertIn("read", got["note"].lower())

    def test_rejects_path_traversal(self):
        bundle = load_bundle_dir(SPECKY)
        from fda.bundle import BundleError, read_artifact_recipe
        with self.assertRaises(BundleError):
            read_artifact_recipe(bundle, "../fda-agent")


if __name__ == "__main__":
    unittest.main()
