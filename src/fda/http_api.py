"""JSON HTTP adapter for products that do not use Python or MCP.

One process can serve many tenants: pass ``X-FDA-Tenant`` and ``X-FDA-Actor``
headers, and the SDK view scopes every call and audit entry accordingly.

    fda api serve --port 8080 --token "$PRODUCT_TOKEN"
"""
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .bundle import BundleError
from .connectors import ConnectorError
from .plays import PlayError
from .privacy import PrivacyError
from .sdk import Client
from .util import utc_now

MAX_BODY = 1024 * 1024


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class APIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FDA-API/0.4"

    @property
    def sdk(self) -> Client:
        return self.server.sdk

    def _send(self, status: int, payload: dict, extra_headers=None) -> None:
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self.server, "allow_origin", ""):
            self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, X-FDA-Tenant, X-FDA-Actor")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = getattr(self.server, "token", "")
        if not token:
            return True
        supplied = self.headers.get("Authorization", "")
        if supplied.startswith("Bearer "):
            supplied = supplied[7:]
        return hmac.compare_digest(supplied, token)

    def _scoped(self) -> Client:
        tenant = self.headers.get("X-FDA-Tenant", "")
        actor = self.headers.get("X-FDA-Actor", "")
        return self.sdk.as_tenant(tenant, actor) if (tenant or actor) else self.sdk

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY:
            raise APIError(413, "request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "body must be JSON")
        if not isinstance(payload, dict):
            raise APIError(400, "body must be a JSON object")
        return payload

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parts[:1] != ["v1"]:
            raise APIError(404, "unknown API version")
        if parsed.path.rstrip("/").endswith("/health") and method == "GET":
            return self._send(200, {"ok": True, "version": __version__,
                                    "ts": utc_now()})
        if not self._authorized():
            raise APIError(401, "invalid bearer token")
        client = self._scoped()
        query = self._query()

        if method == "GET":
            return self._get(client, parts, query)
        if method == "POST":
            return self._post(client, parts)
        raise APIError(405, "method not allowed")

    def _get(self, client: Client, parts, query) -> None:
        if parts == ["v1", "agents"]:
            return self._send(200, client.list_agents())
        if len(parts) == 3 and parts[1] == "agents":
            return self._send(200, client.describe_agent(parts[2]))
        if len(parts) == 4 and parts[1] == "agents" and parts[3] == "skill":
            return self._send(200, {"agent_id": parts[2],
                                    "skill": client.agent_skill(parts[2])})
        if parts == ["v1", "plays"]:
            return self._send(200, client.list_plays())
        if len(parts) == 3 and parts[1] == "plays":
            return self._send(200, client.describe_play(parts[2]))
        if len(parts) == 3 and parts[1] == "runs":
            return self._send(200, client.status(parts[2]).to_dict())
        if parts == ["v1", "approvals"]:
            status = query.get("status", [None])[0]
            limit = int(query.get("limit", ["50"])[0])
            rows = client.runtime.state.approval_list(status, limit) \
                if client.runtime.state else []
            return self._send(200, {"approvals": rows, "count": len(rows)})
        if parts == ["v1", "audit"]:
            limit = int(query.get("limit", ["30"])[0])
            return self._send(200, client.audit(limit))
        if parts == ["v1", "ops", "status"]:
            return self._send(200, client.ops_status())
        if parts == ["v1", "events"]:
            limit = int(query.get("limit", ["50"])[0])
            return self._send(200, {"events": client.events.history(
                limit, query.get("name", [""])[0])})
        raise APIError(404, "not found")

    def _post(self, client: Client, parts) -> None:
        body = self._body()
        if parts == ["v1", "plans"]:
            if not body.get("play_id"):
                raise APIError(400, "play_id is required")
            return self._send(201, client.plan(body["play_id"], body.get("context")))
        if parts == ["v1", "runs"]:
            if not body.get("play_id"):
                raise APIError(400, "play_id is required")
            result = client.run(body["play_id"], body.get("approvals"),
                                body.get("context"))
            return self._send(201 if result.ok else 403, result.to_dict())
        if len(parts) == 4 and parts[1] == "approvals" and parts[3] in ("grant", "deny"):
            approver = body.get("approver", "")
            if not approver:
                raise APIError(400, "approver is required")
            decision = (client.grant_approval if parts[3] == "grant"
                        else client.deny_approval)
            return self._send(200, decision(parts[2], approver))
        if parts == ["v1", "ops", "pause"]:
            return self._send(200, client.pause(body.get("scope", "*"),
                                                body.get("reason", "")))
        if parts == ["v1", "ops", "resume"]:
            return self._send(200, client.resume(body.get("scope", "*")))
        if parts == ["v1", "agents", "install"]:
            if not body.get("archive"):
                raise APIError(400, "archive path is required")
            return self._send(201, client.install_agent(
                body["archive"], force=bool(body.get("force")),
                verify=bool(body.get("verify")),
                registry_check=bool(body.get("registry_check")),
                pin=bool(body.get("pin"))))
        raise APIError(404, "not found")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        try:
            self._send(204, {})
        except Exception:
            pass

    def _handle(self, method: str) -> None:
        try:
            self._dispatch(method)
        except APIError as exc:
            self._send(exc.status, {"error": str(exc)})
        except (KeyError, ValueError, TypeError, PrivacyError, ConnectorError,
                PlayError, BundleError, FileNotFoundError, OSError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # never leak a traceback to a product client
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def log_message(self, fmt, *args):
        # Business data must not reach stdout/stderr; the audit is the record.
        pass


def create_server(client: Client, host: str = "127.0.0.1", port: int = 8080,
                  token: str = "", allow_origin: str = "") -> ThreadingHTTPServer:
    """Build a ready-to-run HTTP server around an SDK client."""
    server = ThreadingHTTPServer((host, port), APIHandler)
    server.sdk = client
    server.token = token
    server.allow_origin = allow_origin
    return server


def serve(client: Client, host: str = "127.0.0.1", port: int = 8080,
          token: str = "", allow_origin: str = "") -> ThreadingHTTPServer:
    """Block and serve the JSON API until interrupted."""
    server = create_server(client, host, port, token, allow_origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server
