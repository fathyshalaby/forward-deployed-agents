import unittest

from scripts.scenarios import SCENARIOS


class ScenarioTests(unittest.TestCase):
    def test_all_scenarios_behave_as_expected(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.name):
                run, runtime = scenario.runner()
                self.assertEqual(run["status"], scenario.expectation)
                denied = [entry for entry in runtime.audit.entries
                          if entry.get("decision") == "deny"]
                if scenario.expectation == "denied":
                    self.assertGreaterEqual(len(denied), 1)
                else:
                    self.assertEqual(len(denied), 0)


if __name__ == "__main__":
    unittest.main()
