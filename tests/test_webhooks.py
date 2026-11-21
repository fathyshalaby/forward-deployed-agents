"""Tests for language-agnostic webhook connector handlers."""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fda import runtime
from fda.connectors import ConnectorError, ConnectorRegistry, WebhookHandler


class CaptureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append((raw, headers))
        body = json.dumps({"created": True, "ref": "INC-42"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.url = "http://127.0.0.1:%d/handle" % self.server.server_address[1]

    def test_webhook_sends_only_capability_context_with_signature(self):
        handler = WebhookHandler(self.url, secret="s3cr3t")
        result = handler({
            "connector": "tickets",
            "action": "acme.support-triage::tickets.create",
            "scopes": ["read", "write"],
            "needs": ["metadata"],
        })
        self.assertEqual(result["ref"], "INC-42")
        raw, headers = self.server.requests[0]
        payload = json.loads(raw)
        self.assertEqual(set(payload), {"connector", "action", "scopes", "needs"})
        expected = "sha256=" + hmac.new(b"s3cr3t", raw, hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-fda-signature"], expected)

    def test_registry_call_uses_bound_webhook(self):
        registry = ConnectorRegistry([{
            "id": "tickets", "name": "Tickets", "scopes": ["read", "write"],
            "actions": ["tickets.create"], "approval_required": ["tickets.create"],
        }])
        registry.bind_webhook("tickets.create", self.url)
        result = registry.call("tickets", "tickets.create",
                               scopes=["read"], needs=["metadata"])
        self.assertTrue(result["created"])
        self.assertEqual(result["mode"], "adapter")
        self.assertEqual(result["needs"], ["metadata"])

    def test_handler_failure_fails_closed_without_leaking_url(self):
        handler = WebhookHandler("http://127.0.0.1:1/nope", timeout=0.2)
        with self.assertRaises(ConnectorError) as caught:
            handler({"connector": "x", "action": "x.y"})
        self.assertNotIn("127.0.0.1", str(caught.exception))

    def test_fda_handlers_env_binds_webhooks(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Path(tmp.name) / "handlers.json"
        config.write_text(json.dumps({
            "tickets.create": {
                "url": self.url, "secret_env": "FDA_TEST_HANDLER_SECRET",
            }
        }))
        connectors = ConnectorRegistry([{
            "id": "tickets", "name": "Tickets", "scopes": ["read"],
            "actions": ["tickets.create"],
        }])
        with mock.patch.dict(os.environ, {
            "FDA_HANDLERS": str(config),
            "FDA_TEST_HANDLER_SECRET": "env-secret",
        }):
            runtime._bind_webhooks(connectors)
        result = connectors.call("tickets", "tickets.create", scopes=["read"])
        self.assertTrue(result["created"])
        raw, headers = self.server.requests[-1]
        expected = "sha256=" + hmac.new(b"env-secret", raw,
                                        hashlib.sha256).hexdigest()
        self.assertEqual(headers["x-fda-signature"], expected)

    def test_bad_handler_config_fails_closed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Path(tmp.name) / "handlers.json"
        config.write_text(json.dumps({"tickets.create": {"no_url": True}}))
        with mock.patch.dict(os.environ, {"FDA_HANDLERS": str(config)}):
            with self.assertRaises(ValueError):
                runtime._bind_webhooks(ConnectorRegistry())


if __name__ == "__main__":
    unittest.main()
