"""Signing, trust, registry and pinning for installable agent bundles.

Stdlib only. Signatures are HMAC-SHA256 over a canonical manifest of file
hashes, with publisher keys held in a local trust store. This gives tamper
detection and explicit trust, not non-repudiation: see docs/security.md for the
difference and the production upgrade path.
"""
import hashlib
import hmac
import json
import os
import secrets
import shutil
import urllib.request
from pathlib import Path

from .util import utc_now

SIGNATURE_FILE = "signature.json"
SIG_SCHEMA = "fda-signature/v1"
REGISTRY_SCHEMA = "fda-registry/v1"
ALG = "hmac-sha256"
TRUST_SCHEMA = "fda-trust/v1"

EXCLUDED_FILES = frozenset({"signature.json", ".fda-install.json"})


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def file_hashes(root, exclude=EXCLUDED_FILES) -> dict:
    """Map every packaged path to its sha256, deterministically."""
    root = Path(root)
    hashes = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude or path.suffix == ".fda":
            continue
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def content_hash(root) -> str:
    """One stable hash for the executable content of a bundle."""
    hashes = file_hashes(root)
    payload = "".join("%s\0%s\n" % (name, hashes[name]) for name in sorted(hashes))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_trust_path() -> Path:
    return Path(os.environ.get("FDA_TRUST") or
                (Path.home() / ".fda" / "trust.json"))


def default_signing_key_path() -> Path:
    return Path(os.environ.get("FDA_SIGNING_KEY") or
                (Path.home() / ".fda" / "keys" / "default.key"))


def generate_key(key_id: str, publisher: str, path=None) -> dict:
    """Create a signing key file. Treat its secret like a private key."""
    destination = Path(path) if path else default_signing_key_path()
    record = {
        "schema": "fda-key/v1",
        "key_id": key_id,
        "publisher": publisher,
        "secret": secrets.token_urlsafe(32),
        "created_at": utc_now(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return record


def read_key(path) -> dict:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("schema") != "fda-key/v1" or not record.get("secret"):
        raise ValueError("not a valid fda key file")
    return record


class Keyring:
    def __init__(self, path=None, require_signature=None):
        self.path = Path(path) if path else default_trust_path()
        self.data = {"schema": TRUST_SCHEMA, "keys": {},
                     "require_signature": False}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        env_require = os.environ.get("FDA_REQUIRE_SIGNATURE", "")
        if require_signature is not None:
            self.data["require_signature"] = bool(require_signature)
        elif env_require in ("1", "true", "yes"):
            self.data["require_signature"] = True

    def add(self, key_record: dict) -> None:
        self.data["keys"][key_record["key_id"]] = {
            "secret": key_record["secret"],
            "publisher": key_record.get("publisher", ""),
            "added_at": utc_now(),
        }
        self.save()

    def remove(self, key_id: str) -> bool:
        removed = self.data["keys"].pop(key_id, None) is not None
        if removed:
            self.save()
        return removed

    def set_required(self, required: bool) -> None:
        self.data["require_signature"] = bool(required)
        self.save()

    def require(self) -> bool:
        return bool(self.data.get("require_signature"))

    def get(self, key_id: str):
        entry = self.data["keys"].get(key_id)
        return entry["secret"] if entry else None

    def list(self) -> list:
        return [{"key_id": key_id, "publisher": value.get("publisher", ""),
                 "added_at": value.get("added_at", "")}
                for key_id, value in sorted(self.data["keys"].items())]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


class Signer:
    def __init__(self, key_id: str, secret: str):
        self.key_id = key_id
        self.secret = secret.encode("utf-8")

    @classmethod
    def from_keyfile(cls, path=None):
        record = read_key(path or default_signing_key_path())
        return cls(record["key_id"], record["secret"])

    def signature_for(self, root) -> dict:
        files = file_hashes(root)
        payload = {"schema": SIG_SCHEMA, "alg": ALG,
                   "key_id": self.key_id, "files": files}
        value = hmac.new(self.secret, canonical(payload), hashlib.sha256).hexdigest()
        return {**payload, "value": value, "signed_at": utc_now()}


class Verifier:
    def __init__(self, keyring: Keyring, require: bool = None):
        self.keyring = keyring
        self.require = keyring.require() if require is None else require

    def verify(self, root) -> dict:
        """Verify a bundle directory. Raises ValueError on failure."""
        path = Path(root) / SIGNATURE_FILE
        if not path.is_file():
            if self.require:
                raise ValueError("bundle is unsigned but a signature is required")
            return {"verified": False, "reason": "unsigned"}
        signature = json.loads(path.read_text(encoding="utf-8"))
        if signature.get("schema") != SIG_SCHEMA or signature.get("alg") != ALG:
            raise ValueError("unsupported signature format")
        payload = {key: signature.get(key)
                   for key in ("schema", "alg", "key_id", "files")}
        secret = self.keyring.get(signature.get("key_id", ""))
        if not secret:
            raise ValueError("untrusted signing key: %s" % signature.get("key_id"))
        expected = hmac.new(secret.encode("utf-8"), canonical(payload),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.get("value", "")):
            raise ValueError("bundle signature does not match")
        actual = file_hashes(root)
        if actual != signature.get("files"):
            missing = sorted(set(actual) ^ set(signature.get("files") or {}))
            raise ValueError("bundle files changed after signing: %s" % missing[:5])
        return {"verified": True, "key_id": signature["key_id"],
                "publisher": self.keyring.data["keys"][signature["key_id"]].get(
                    "publisher", ""),
                "files": len(actual)}


def default_registry_path() -> Path:
    return Path(os.environ.get("FDA_REGISTRY") or
                (Path.home() / ".fda" / "registry"))


class Registry:
    """A publish/verify index. Local by default; remote index is read-only."""

    def __init__(self, root=None):
        root = Path(root) if root else default_registry_path()
        self.root = root
        self.remote = str(root).startswith(("http://", "https://"))
        self.index_path = (root if self.remote else root / "index.json")

    def load(self) -> dict:
        if self.remote:
            with urllib.request.urlopen(str(self.index_path), timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        if not self.index_path.exists():
            return {"schema": REGISTRY_SCHEMA, "entries": {}, "revocations": []}
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        if data.get("schema") != REGISTRY_SCHEMA:
            raise ValueError("unsupported registry schema")
        return data

    def save(self, data: dict) -> None:
        if self.remote:
            raise ValueError("remote registries are read-only")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def init(self) -> dict:
        data = self.load() if not self.remote and self.index_path.exists() else {
            "schema": REGISTRY_SCHEMA, "entries": {}, "revocations": []}
        self.save(data)
        return data

    def publish(self, archive, verifier=None, key_id="", publisher="") -> dict:
        archive = Path(archive)
        if self.remote:
            raise ValueError("remote registries are read-only")
        if verifier:
            import zipfile
            import tempfile
            from .bundle import _safe_extract
            with tempfile.TemporaryDirectory(prefix="fda-registry-") as tmp:
                staging = Path(tmp) / "bundle"
                staging.mkdir()
                with zipfile.ZipFile(archive) as zipf:
                    _safe_extract(zipf, staging)
                verifier.verify(staging)
        data = self.load()
        bundle_id, version = _id_version_from_archive(archive)
        archive_dir = self.root / "archives" / bundle_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / ("%s-%s%s" % (bundle_id, version, ".fda"))
        shutil.copyfile(archive, destination)
        entry = {
            "id": bundle_id,
            "version": version,
            "archive": str(destination),
            "sha256": sha256_file(destination),
            "publisher": publisher or key_id,
            "key_id": key_id,
            "published_at": utc_now(),
        }
        data["entries"].setdefault(bundle_id, {})[version] = entry
        self.save(data)
        return entry

    def list(self) -> list:
        data = self.load()
        rows = []
        for bundle_id, versions in data.get("entries", {}).items():
            for version, entry in versions.items():
                rows.append(entry)
        return sorted(rows, key=lambda row: (row["id"], row["version"]))

    def get(self, bundle_id: str, version: str = "") -> dict:
        data = self.load()
        versions = data.get("entries", {}).get(bundle_id, {})
        if version:
            return versions.get(version, {})
        if not versions:
            return {}
        latest = sorted(versions, key=lambda value: value)[-1]
        return versions[latest]

    def revoke(self, bundle_id: str, version: str = "*", reason: str = "") -> dict:
        if self.remote:
            raise ValueError("remote registries are read-only")
        record = {"bundle_id": bundle_id, "version": version,
                  "reason": reason, "revoked_at": utc_now()}
        data = self.load()
        data["revocations"] = [row for row in data.get("revocations", [])
                               if not (row["bundle_id"] == bundle_id
                                       and row["version"] == version)]
        data["revocations"].append(record)
        self.save(data)
        return record

    def revoked(self) -> list:
        return self.load().get("revocations", [])

    def is_revoked(self, bundle_id: str, version: str = "") -> bool:
        for row in self.revoked():
            if row["bundle_id"] == bundle_id and row["version"] in ("*", version):
                return True
        return False


def _id_version_from_archive(archive: Path):
    """Read identity from the archive manifest, not its file name."""
    import zipfile
    from .bundle import MANIFEST_FILE

    with zipfile.ZipFile(archive) as zipf:
        manifest = json.loads(zipf.read(MANIFEST_FILE).decode("utf-8"))
    return manifest["id"], manifest["version"]
