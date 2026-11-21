"""HTTP/SSE transport for the MCP server.

ChatGPT custom MCP plugins speak SSE or streaming HTTP over a URL; only local
clients such as Claude Desktop and Claude Code can spawn a stdio server. This
module exposes the *same* MCPServer over HTTP with the standard library only.

Endpoints
    GET  /health  public liveness probe
    POST /mcp     JSON-RPC message or batch; replies as JSON or SSE
    GET  /mcp     SSE stream for server-to-client messages and heartbeats
    DELETE /mcp   session termination (no-op; kept for spec compliance)

Set ``token`` to require ``Authorization: Bearer <token>`` on /mcp. ChatGPT's
custom MCP form offers OAuth or no authentication, so for ChatGPT put this
behind a trusted network, Secure MCP Tunnel, or an OAuth proxy. Clients that
can send headers (Claude remote connectors) can use the bearer token directly.
"""
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__
from .mcp import MCPServer
from .util import new_id, utc_now

MAX_BODY = 1024 * 1024


class MCPHTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class MCPHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FDA-MCP/" + __version__

    @property
    def mcp(self):
        return self.server.mcp

    def _authorized(self):
        token = getattr(self.server, "token", "")
        if not token:
            return True
        supplied = self.headers.get("Authorization", "")
        if supplied.startswith("Bearer "):
            supplied = supplied[7:]
        return hmac.compare_digest(supplied, token)

    def _send(self, status, payload=None, content_type="application/json",
              headers=None, close=True):
        body = b""
        if payload is not None:
            body = (payload if isinstance(payload, bytes) else
                    json.dumps(payload, sort_keys=True).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        if body or payload is not None:
            self.send_header("Content-Length", str(len(body)))
        if getattr(self.server, "allow_origin", ""):
            self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, Mcp-Session-Id")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, DELETE, OPTIONS")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _session(self):
        return self.headers.get("Mcp-Session-Id", "") or new_id("s", 12)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY:
            raise MCPHTTPError(413, "request body too large")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MCPHTTPError(400, "body must be JSON")
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return payload
        raise MCPHTTPError(400, "body must be a JSON object or array")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        try:
            self._send(204)
        except Exception:
            pass

    def _handle(self, method):
        try:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/health" and method == "GET":
                return self._send(200, {"ok": True, "version": __version__,
                                        "transport": "http/sse", "ts": utc_now()})
            if path != "/mcp":
                raise MCPHTTPError(404, "not found")
            if not self._authorized():
                raise MCPHTTPError(401, "invalid bearer token")
            if method == "DELETE":
                return self._send(204)
            if method == "GET":
                return self._stream()
            if method == "POST":
                return self._rpc()
            raise MCPHTTPError(405, "method not allowed")
        except MCPHTTPError as exc:
            self._send(exc.status, {"error": str(exc)})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # never leak a traceback to a client
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _rpc(self):
        messages = self._body()
        responses = [response for message in messages
                     for response in [self.mcp.handle(message)]
                     if response is not None]
        session = self._session()
        headers = {"Mcp-Session-Id": session}
        if not responses:
            return self._send(202, headers=headers)
        accept = self.headers.get("Accept", "")
        if "text/event-stream" in accept:
            chunks = [b": connected\n\n"]
            for response in responses:
                data = json.dumps(response, sort_keys=True).encode("utf-8")
                chunks.append(b"event: message\ndata: " + data + b"\n\n")
            body = b"".join(chunks)
            return self._send(200, body, "text/event-stream; charset=utf-8", headers)
        payload = responses[0] if len(responses) == 1 else responses
        return self._send(200, payload, headers=headers)

    def _stream(self):
        """Keep an SSE stream open with heartbeats until the client disconnects."""
        session = self._session()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("Mcp-Session-Id", session)
        if getattr(self.server, "allow_origin", ""):
            self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while not getattr(self.server, "shutdown_flag", False):
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                time.sleep(15)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, fmt, *args):
        # Business data must never reach stdout/stderr; the audit is the record.
        pass


def create_server(runtime, host="127.0.0.1", port=8000, token="",
                  allow_origin=""):
    """Build a ready-to-run HTTP MCP server around a runtime."""
    server = ThreadingHTTPServer((host, port), MCPHTTPHandler)
    server.mcp = MCPServer(runtime)
    server.token = token
    server.allow_origin = allow_origin
    server.shutdown_flag = False
    server.daemon_threads = True
    return server


def serve(runtime, host="127.0.0.1", port=8000, token="", allow_origin=""):
    """Block and serve MCP over HTTP until interrupted."""
    server = create_server(runtime, host, port, token, allow_origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_flag = True
        server.server_close()
    return server
