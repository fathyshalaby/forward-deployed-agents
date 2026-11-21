"""Durable state: runs, approvals, audit, revocations, pins and kill switch.

Standard library only (sqlite3). Every table lives in one SQLite file inside the
customer boundary. The audit table is hash-chained so a edited row is visible.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .util import utc_now


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class StateStore:
    """One SQLite database holding the control-plane state of the runtime."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    tenant TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    play TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    needs TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT '',
                    playbook_hash TEXT NOT NULL DEFAULT '',
                    args_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    granted_by TEXT NOT NULL DEFAULT '',
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at REAL NOT NULL DEFAULT 0,
                    decided_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    tenant TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    tool TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revocations (
                    bundle_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    revoked_at TEXT NOT NULL,
                    PRIMARY KEY (bundle_id, version)
                );
                CREATE TABLE IF NOT EXISTS pins (
                    bundle_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    pinned_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kill_switch (
                    scope TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
                CREATE INDEX IF NOT EXISTS idx_runs_tenant ON runs(tenant);
            """)

    # ------------------------------------------------------------------ runs
    def run_save(self, run, tenant="", actor=""):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, tenant, actor, play, status, payload, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (run["run_id"], tenant, actor, run.get("play", ""),
                 run.get("status", ""), _json(run), utc_now()),
            )
        return run

    def run_get(self, run_id):
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?",
                               (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def run_list(self, tenant="", limit=30):
        with self._connect() as conn:
            if tenant:
                rows = conn.execute(
                    "SELECT payload FROM runs WHERE tenant=? "
                    "ORDER BY created_at DESC LIMIT ?", (tenant, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    # ------------------------------------------------------------- approvals
    def approval_save(self, record):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approvals "
                "(id, action, reason, needs, purpose, actor, playbook_hash, "
                " args_hash, status, granted_by, used, created_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record["id"], record["action"], record["reason"],
                 _json(record["needs"]), record["purpose"], record.get("actor", ""),
                 record.get("playbook_hash", ""), record.get("args_hash", ""),
                 record.get("status", "pending"), record.get("granted_by", ""),
                 int(record.get("used", False)), record.get("created_at", utc_now()),
                 float(record.get("expires_at", 0))),
            )

    def approval_get(self, approval_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id=?",
                               (approval_id,)).fetchone()
        return dict(row) if row else None

    def approval_list(self, status=None, limit=50):
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status=? "
                    "ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
        return [dict(row) for row in rows]

    def approval_decide(self, approval_id, decision, approver):
        """Atomic decision. Returns (ok, reason)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE id=?",
                               (approval_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False, "unknown approval id"
            if row["status"] != "pending":
                conn.execute("ROLLBACK")
                return False, "approval already decided"
            now = time.time()
            if row["expires_at"] and now > row["expires_at"]:
                conn.execute("ROLLBACK")
                return False, "approval expired"
            status = "granted" if decision == "grant" else "denied"
            conn.execute(
                "UPDATE approvals SET status=?, granted_by=?, decided_at=? WHERE id=?",
                (status, approver, utc_now(), approval_id),
            )
        return True, status

    def approval_consume(self, approval_id, action, needs, purpose,
                         actor=None, playbook_hash=None, args_hash=None):
        """Single-use consumption with all bindings checked atomically."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE id=?",
                               (approval_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None, "unknown approval id"
            if row["status"] != "granted":
                conn.execute("ROLLBACK")
                return None, "approval not granted"
            if row["used"]:
                conn.execute("ROLLBACK")
                return None, "approval already used"
            if row["expires_at"] and time.time() > row["expires_at"]:
                conn.execute("ROLLBACK")
                return None, "approval expired"
            if row["action"] != action:
                conn.execute("ROLLBACK")
                return None, "approval is for a different action"
            if row["purpose"] != purpose:
                conn.execute("ROLLBACK")
                return None, "approval purpose does not match"
            if not set(needs).issubset(set(json.loads(row["needs"]))):
                conn.execute("ROLLBACK")
                return None, "approval does not cover all requested data classes"
            for field, expected in (("actor", actor),
                                    ("playbook_hash", playbook_hash),
                                    ("args_hash", args_hash)):
                if row[field] and expected and row[field] != expected:
                    conn.execute("ROLLBACK")
                    return None, "approval %s does not match" % field
            conn.execute("UPDATE approvals SET used=1 WHERE id=?", (approval_id,))
        return dict(row), ""

    # ------------------------------------------------------------------ audit
    def audit_append(self, entry, tenant="", actor=""):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            last = conn.execute(
                "SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else "0" * 64
            stored = dict(entry)
            stored["tenant"] = tenant
            stored["actor"] = actor
            digest = hashlib.sha256(
                (_json(stored) + prev).encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO audit (ts, tenant, actor, tool, decision, "
                "prev_hash, hash, payload) VALUES (?,?,?,?,?,?,?,?)",
                (entry.get("ts", utc_now()), tenant, actor,
                 entry.get("tool", ""), entry.get("decision", ""),
                 prev, digest, _json(stored)),
            )
        return digest

    def audit_list(self, limit=30):
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
            rows = conn.execute(
                "SELECT seq, hash, prev_hash, payload FROM audit "
                "ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        entries = []
        for row in reversed(rows):
            payload = json.loads(row["payload"])
            payload["_seq"] = row["seq"]
            payload["_hash"] = row["hash"]
            entries.append(payload)
        return {"entries": total, "shown": len(entries), "timeline": entries}

    def audit_verify(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, hash, prev_hash, payload FROM audit ORDER BY seq"
            ).fetchall()
        previous = "0" * 64
        broken = []
        for row in rows:
            payload = json.loads(row["payload"])
            expected = hashlib.sha256(
                (_json(payload) + previous).encode("utf-8")).hexdigest()
            if row["prev_hash"] != previous or row["hash"] != expected:
                broken.append(row["seq"])
            previous = row["hash"]
        return {"entries": len(rows), "ok": not broken, "broken_seq": broken}

    # --------------------------------------------------------------- policy
    def revoke(self, bundle_id, version="*", reason=""):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO revocations VALUES (?,?,?,?)",
                (bundle_id, version, reason, utc_now()),
            )

    def is_revoked(self, bundle_id, version=""):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM revocations WHERE bundle_id=? AND version IN ('*',?) "
                "LIMIT 1", (bundle_id, version)).fetchone()
        return row is not None

    def revocations(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM revocations ORDER BY revoked_at DESC").fetchall()
        return [dict(row) for row in rows]

    def pin(self, bundle_id, content_hash):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pins VALUES (?,?,?)",
                (bundle_id, content_hash, utc_now()),
            )

    def unpin(self, bundle_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM pins WHERE bundle_id=?", (bundle_id,))

    def pin_get(self, bundle_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pins WHERE bundle_id=?",
                               (bundle_id,)).fetchone()
        return dict(row) if row else None

    def kill_set(self, scope, paused, reason=""):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kill_switch VALUES (?,?,?,?)",
                (scope, int(bool(paused)), reason, utc_now()),
            )

    def kill_check(self, tenant=""):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM kill_switch").fetchall()
        for row in rows:
            if row["scope"] in ("*", tenant) and row["paused"]:
                return {"paused": True, "scope": row["scope"],
                        "reason": row["reason"]}
        return {"paused": False, "scope": "", "reason": ""}

    def kill_status(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM kill_switch ORDER BY scope").fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self._connect() as conn:
            runs = conn.execute(
                "SELECT status, COUNT(*) AS n FROM runs GROUP BY status").fetchall()
            approvals = conn.execute(
                "SELECT status, COUNT(*) AS n FROM approvals GROUP BY status").fetchall()
            audit = conn.execute(
                "SELECT decision, COUNT(*) AS n FROM audit GROUP BY decision").fetchall()
        return {
            "runs": {row["status"]: row["n"] for row in runs},
            "approvals": {row["status"]: row["n"] for row in approvals},
            "audit": {row["decision"]: row["n"] for row in audit},
        }
