"""Small shared helpers. Standard library only."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SECRET = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|(?:gh[pousr]_[A-Za-z0-9]{8,})"
    r"|(?:Bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


def new_id(prefix: str, length: int = 12) -> str:
    return "%s%s" % (prefix, hashlib.sha256(_token()).hexdigest()[:length])


def _token() -> bytes:
    import os
    return os.urandom(32)


def text_hash(value: str) -> str:
    """Stable short hash so free text can be referenced without being stored."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def redact(value: str) -> str:
    return _SECRET.sub("[redacted]", str(value))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
