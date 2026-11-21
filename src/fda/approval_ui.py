"""Minimal out-of-band approval UI over local HTTP.

This is the customer approval surface: it writes to the same SQLite store the
runtime reads. The MCP client does not know the approver token, so model output
cannot forge a grant. Bind to loopback by default and put TLS/auth in front of
it for real deployments.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .store import StateStore
from .util import utc_now

TOKEN_HEADER = "X-FDA-Token"


class ApprovalHandler(BaseHTTPRequestHandler):
    server_version = "FDA-Approvals/0.3"

    @property
    def state(self) -> StateStore:
        return self.server.state

    def _send(self, status, payload):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return self.headers.get(TOKEN_HEADER, "") == self.server.token

    def _body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            return self._send(200, {"ok": True, "ts": utc_now()})
        if not self._authorized():
            return self._send(401, {"error": "invalid approver token"})
        if parsed.path == "/approvals":
            status = parse_qs(parsed.query).get("status", [None])[0]
            return self._send(200, {"approvals": self.state.approval_list(status)})
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 2 and parts[0] == "approvals":
            record = self.state.approval_get(parts[1])
            return self._send(200, record) if record else self._send(
                404, {"error": "unknown approval"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return self._send(401, {"error": "invalid approver token"})
        parts = [part for part in urlparse(self.path).path.split("/") if part]
        if len(parts) != 3 or parts[0] != "approvals" or parts[2] not in ("grant", "deny"):
            return self._send(404, {"error": "not found"})
        payload = self._body()
        approver = str(payload.get("approver", "")).strip()
        if not approver:
            return self._send(400, {"error": "approver is required"})
        ok, status = self.state.approval_decide(parts[1], parts[2], approver)
        if not ok:
            return self._send(409, {"error": status})
        self.state.audit_append(
            {"ts": utc_now(), "tool": "approval.%s" % parts[2],
             "decision": status, "approval_id": parts[1], "approver": approver,
             "actor": "approver"},
            actor="approver",
        )
        return self._send(200, {"approval_id": parts[1], "status": status,
                                "approver": approver})

    def log_message(self, fmt, *args):
        # Diagnostics only; never log request bodies or approval content.
        pass


def serve(state_path, token, host="127.0.0.1", port=8787):
    """Block and serve the approval UI."""
    server = ThreadingHTTPServer((host, port), ApprovalHandler)
    server.state = StateStore(state_path)
    server.token = token
    return server
