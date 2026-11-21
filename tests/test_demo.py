import contextlib
import io
import unittest

from fda import demo


class DemoTests(unittest.TestCase):
    def test_demo_runs_and_shows_gate(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = demo.main()
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("play.plan: approvals issued", text)
        self.assertIn("content without approval (fail closed)", text)
        self.assertIn("Demo done", text)
        self.assertIn("sensitive data requires an approval id", text)


if __name__ == "__main__":
    unittest.main()
