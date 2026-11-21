"""Portable agent bundles.

A bundle is the unit a builder creates and a user installs. It packages
playbooks, connector descriptors and an optional AI skill behind one versioned
manifest. Bundles are namespaced on load, so two agents can ship a connector
called ``tickets`` without colliding.

The format is deliberately declarative. Bundles never carry executable code or
credentials; the operator wires real adapters into ``ConnectorRegistry``.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .connectors import _action_key
from .plays import Playbook, load_playbooks
from .util import redact, utc_now

MANIFEST_FILE = "fda-agent.json"
SCHEMA = "fda-agent/v1"
BUNDLE_SUFFIX = ".fda"
RECEIPT_FILE = ".fda-install.json"

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".json", ".md", ".txt", ".yaml", ".yml"})
IGNORED_NAMES = frozenset({".git", ".DS_Store", "__pycache__", RECEIPT_FILE,
                           "signature.json"})

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$")

MANIFEST_KEYS = frozenset({
    "schema", "id", "name", "version", "description", "author", "license",
    "tags", "homepage", "entry", "requires", "capabilities",
})
ENTRY_KEYS = frozenset({"playbooks", "connectors", "skill"})


class BundleError(Exception):
    """Raised for invalid, unsafe or incompatible agent bundles."""


def default_store() -> Path:
    """The local install directory for agent bundles."""
    return Path(os.environ.get("FDA_AGENTS") or (Path.home() / ".fda" / "agents"))


def _string(value, label, errors, required=True, max_length=500):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        errors.append("%s must be a non-empty string" % label)
        return ""
    value = value.strip()
    if len(value) > max_length:
        errors.append("%s is longer than %d characters" % (label, max_length))
    return value


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    playbooks: str = "playbooks"
    connectors: str = "connectors.json"
    skill: str = ""
    requires_fda: str = ""
    capabilities: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw) -> "Manifest":
        if not isinstance(raw, dict):
            raise BundleError("manifest must be a JSON object")
        errors = []
        unknown = sorted(set(raw) - MANIFEST_KEYS)
        if unknown:
            errors.append("unknown manifest fields: %s" % ", ".join(unknown))

        identifier = _string(raw.get("id"), "id", errors, max_length=64)
        if identifier and not ID_RE.match(identifier):
            errors.append("id must be a lowercase slug (letters, digits, . _ -)")
        name = _string(raw.get("name"), "name", errors, max_length=80)
        version = _string(raw.get("version"), "version", errors, max_length=40)
        if version and not VERSION_RE.match(version):
            errors.append("version must look like 1.2.3")
        if raw.get("schema") != SCHEMA:
            errors.append("schema must be %s" % SCHEMA)

        description = _string(raw.get("description"), "description", errors,
                              required=False, max_length=300)
        author = _string(raw.get("author"), "author", errors, required=False)
        license_name = _string(raw.get("license"), "license", errors, required=False)
        homepage = _string(raw.get("homepage"), "homepage", errors, required=False)

        entry = raw.get("entry", {}) or {}
        if not isinstance(entry, dict):
            errors.append("entry must be an object")
            entry = {}
        unknown_entry = sorted(set(entry) - ENTRY_KEYS)
        if unknown_entry:
            errors.append("unknown entry fields: %s" % ", ".join(unknown_entry))
        playbooks = _string(entry.get("playbooks", "playbooks"),
                            "entry.playbooks", errors, required=False)
        connectors = _string(entry.get("connectors", "connectors.json"),
                             "entry.connectors", errors, required=False)
        skill = _string(entry.get("skill"), "entry.skill", errors, required=False)

        requires = raw.get("requires", {}) or {}
        if not isinstance(requires, dict):
            errors.append("requires must be an object")
            requires = {}
        requires_fda = _string(requires.get("fda"), "requires.fda",
                               errors, required=False)

        tags = raw.get("tags", []) or []
        capabilities = raw.get("capabilities", []) or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append("tags must be a list of strings")
            tags = []
        if not isinstance(capabilities, list) or not all(
                isinstance(c, str) for c in capabilities):
            errors.append("capabilities must be a list of strings")
            capabilities = []

        for value in (description, author, homepage, *[str(t) for t in tags]):
            if value and redact(value) != value:
                errors.append("manifest contains secret-like text")
                break

        if errors:
            raise BundleError("; ".join(sorted(set(errors))))
        return cls(
            id=identifier, name=name, version=version, description=description,
            author=author, license=license_name, tags=sorted(set(tags)),
            homepage=homepage, playbooks=playbooks, connectors=connectors,
            skill=skill, requires_fda=requires_fda,
            capabilities=sorted(set(capabilities)),
        )

    def public(self) -> dict:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "tags": self.tags,
            "homepage": self.homepage,
            "entry": {
                "playbooks": self.playbooks,
                "connectors": self.connectors,
                "skill": self.skill,
            },
            "requires": {"fda": self.requires_fda},
            "capabilities": self.capabilities,
        }


@dataclass
class Bundle:
    manifest: Manifest
    root: Path
    playbooks: Dict[str, Playbook] = field(default_factory=dict)
    connectors: List[dict] = field(default_factory=list)
    receipt: dict = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        return self.manifest.id + "::"

    def public(self) -> dict:
        install = {}
        if self.receipt:
            install = {
                key: self.receipt.get(key, "")
                for key in ("installed_at", "sha256", "content_hash",
                            "verified", "publisher", "key_id")
            }
        return {
            **self.manifest.public(),
            "playbook_ids": sorted(self.playbooks),
            "connectors": sorted(c["id"] for c in self.connectors),
            "steps": sum(len(play.steps) for play in self.playbooks.values()),
            "source": str(self.root),
            "install": install,
        }


def _namespace_action(prefix: str, connector_id: str, action: str) -> str:
    """``tickets.create`` -> ``acme.x::tickets.create``."""
    return prefix + _action_key(connector_id, action)


def load_bundle_dir(path, namespace=True, expected_hash="") -> Bundle:
    """Load and validate one bundle directory."""
    root = Path(path).resolve()
    if expected_hash:
        from .security import content_hash
        if content_hash(root) != expected_hash:
            raise BundleError("bundle content hash mismatch: %s" % root)
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.exists():
        raise BundleError("missing %s in %s" % (MANIFEST_FILE, root))
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BundleError("cannot read manifest: %s" % exc)
    manifest = Manifest.from_dict(raw)

    playbook_dir = root / manifest.playbooks
    if not playbook_dir.is_dir():
        raise BundleError("playbook directory not found: %s" % manifest.playbooks)
    try:
        playbooks = load_playbooks(playbook_dir)
    except (ValueError, OSError) as exc:
        raise BundleError("invalid playbook: %s" % exc)

    connector_path = root / manifest.connectors if manifest.connectors else None
    descriptors = []
    if connector_path is not None:
        if not connector_path.is_file():
            raise BundleError("connector file not found: %s" % manifest.connectors)
        try:
            payload = json.loads(connector_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise BundleError("cannot read connectors: %s" % exc)
        descriptors = payload.get("connectors", []) if isinstance(payload, dict) else payload
        if not isinstance(descriptors, list) or not all(
                isinstance(item, dict) for item in descriptors):
            raise BundleError("connectors must be a JSON list of descriptors")

    granted = {item.get("id") for item in descriptors}
    for play in playbooks.values():
        for step in play.steps:
            if step.tool == "connectors.call" and step.connector not in granted:
                raise BundleError(
                    "play %s step %s uses undeclared connector %s"
                    % (play.id, step.id, step.connector)
                )

    receipt = {}
    receipt_path = root / RECEIPT_FILE
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            receipt = {}

    if not namespace:
        return Bundle(manifest, root, playbooks, descriptors, receipt)

    prefix = manifest.id + "::"
    namespaced_books = {}
    for old_id, play in playbooks.items():
        play.id = prefix + old_id
        for step in play.steps:
            if step.tool == "connectors.call":
                original = step.connector
                step.connector = prefix + original
                step.action = _namespace_action(prefix, original, step.action)
        namespaced_books[play.id] = play

    namespaced_connectors = []
    for descriptor in descriptors:
        item = dict(descriptor)
        original = item["id"]
        item["id"] = prefix + original
        item["actions"] = [
            _namespace_action(prefix, original, action)
            for action in item.get("actions", [])
        ]
        item["approval_required"] = [
            _namespace_action(prefix, original, action)
            for action in item.get("approval_required", [])
        ]
        namespaced_connectors.append(item)
    return Bundle(manifest, root, namespaced_books, namespaced_connectors, receipt)


def validate_bundle_dir(path) -> dict:
    """Return a report without installing anything."""
    bundle = load_bundle_dir(path)
    warnings = []
    for play in bundle.playbooks.values():
        for step in play.steps:
            if "content" in step.needs:
                warnings.append("step %s reads content (needs purpose + approval)" % step.id)
            if "identifier" in step.needs:
                warnings.append("step %s reads identifiers" % step.id)
    return {
        "ok": True,
        **bundle.public(),
        "warnings": warnings,
    }


def _iter_bundle_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if any(part in IGNORED_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix == BUNDLE_SUFFIX or name.endswith(".pyc"):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise BundleError("unsupported file type in bundle: %s" % name)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise BundleError("file too large in bundle: %s" % name)
        yield path


def build_bundle(source_dir, output=None, signer=None) -> Path:
    """Package a validated bundle directory into a single ``.fda`` archive.

    A signer, when supplied, writes ``signature.json`` into the archive. It is
    never read from the source directory, so a stale signature cannot leak.
    """
    bundle = load_bundle_dir(source_dir)
    root = bundle.root
    destination = Path(output) if output else Path.cwd() / (
        "%s-%s%s" % (bundle.manifest.id, bundle.manifest.version, BUNDLE_SUFFIX)
    )
    if destination.suffix != BUNDLE_SUFFIX:
        destination = destination.with_suffix(BUNDLE_SUFFIX)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _iter_bundle_files(root):
            total += path.stat().st_size
            if total > MAX_TOTAL_BYTES:
                raise BundleError("bundle exceeds %d bytes" % MAX_TOTAL_BYTES)
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
        if signer:
            from .security import SIGNATURE_FILE
            signature = signer.signature_for(root)
            info = zipfile.ZipInfo(SIGNATURE_FILE,
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, json.dumps(signature, indent=2, sort_keys=True))
    return destination


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> str:
    """Extract a zip without traversal, absolute paths, symlinks or bombs."""
    total = 0
    digest = hashlib.sha256()
    for info in archive.infolist():
        name = info.filename
        if not name or name.startswith("/") or "\\" in name or "\x00" in name:
            raise BundleError("unsafe archive member: %r" % name)
        parts = Path(name).parts
        if ".." in parts or Path(name).is_absolute():
            raise BundleError("unsafe archive member: %r" % name)
        if info.is_dir():
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise BundleError("symlinks are not allowed in bundles")
        if info.file_size > MAX_FILE_BYTES:
            raise BundleError("archive member too large: %s" % name)
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise BundleError("archive too large")
        data = archive.read(info)
        digest.update(data)
        target_path = target.joinpath(*parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
    return digest.hexdigest()


def install_bundle(archive_path, store=None, force=False, verifier=None,
                   registry=None, state=None, pin=False) -> Bundle:
    """Install a ``.fda`` archive into the local agent store.

    Verification order: archive structure -> signature/trust -> registry entry
    and revocation -> durable revocation list -> install. A pinned hash can be
    recorded on install and is checked every time the bundle is loaded.
    """
    from .security import content_hash, sha256_file

    store = Path(store) if store else default_store()
    store.mkdir(parents=True, exist_ok=True)
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise BundleError("archive not found: %s" % archive_path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if MANIFEST_FILE not in archive.namelist():
                raise BundleError("archive has no %s" % MANIFEST_FILE)
            with tempfile.TemporaryDirectory(prefix="fda-install-") as tmp:
                staging = Path(tmp) / "bundle"
                staging.mkdir()
                checksum = _safe_extract(archive, staging)
                bundle = load_bundle_dir(staging)
                identifier = bundle.manifest.id
                version = bundle.manifest.version

                verification = {"verified": False, "reason": "unsigned"}
                if verifier:
                    try:
                        verification = verifier.verify(staging)
                    except ValueError as exc:
                        raise BundleError("signature verification failed: %s" % exc)

                if state and state.is_revoked(identifier, version):
                    raise BundleError("%s %s is revoked" % (identifier, version))
                if registry:
                    entry = registry.get(identifier, version)
                    if not entry:
                        raise BundleError(
                            "%s %s is not published in the registry"
                            % (identifier, version))
                    if registry.is_revoked(identifier, version):
                        raise BundleError("%s is revoked in the registry" % identifier)
                    if entry.get("sha256") and entry["sha256"] != sha256_file(archive_path):
                        raise BundleError("archive sha256 does not match registry entry")

                fingerprint = content_hash(staging)
                destination = store / identifier
                if destination.exists():
                    if not force:
                        raise BundleError(
                            "%s is already installed; use --force to replace"
                            % identifier)
                    shutil.rmtree(destination)
                shutil.move(str(staging), str(destination))
                receipt = {
                    "installed_at": utc_now(),
                    "archive": archive_path.name,
                    "sha256": checksum,
                    "content_hash": fingerprint,
                    "verified": verification.get("verified", False),
                    "publisher": verification.get("publisher", ""),
                    "key_id": verification.get("key_id", ""),
                }
                (destination / RECEIPT_FILE).write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if state and pin:
                    state.pin(identifier, fingerprint)
    except zipfile.BadZipFile as exc:
        raise BundleError("not a valid .fda archive: %s" % exc)
    return load_bundle_dir(store / identifier, expected_hash=fingerprint)


def list_installed(store=None) -> List[dict]:
    store = Path(store) if store else default_store()
    if not store.is_dir():
        return []
    rows = []
    for path in sorted(store.iterdir()):
        if not path.is_dir() or not (path / MANIFEST_FILE).exists():
            continue
        try:
            rows.append(load_bundle_dir(path).public())
        except BundleError:
            rows.append({"id": path.name, "name": path.name, "status": "invalid",
                         "source": str(path)})
    return rows


def uninstall_bundle(identifier: str, store=None) -> bool:
    store = Path(store) if store else default_store()
    destination = store / identifier
    if not destination.is_dir():
        return False
    shutil.rmtree(destination)
    return True


def _skill_name(identifier: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", identifier.lower()).strip("-")


def bundle_skill_text(bundle: Bundle, prefer_custom: bool = True) -> str:
    """Return an AI-client skill markdown document for an installed bundle."""
    if prefer_custom and bundle.manifest.skill:
        path = bundle.root / bundle.manifest.skill
        if path.is_file():
            return path.read_text(encoding="utf-8")

    manifest = bundle.manifest
    plays = "\n".join("- `%s`" % play_id for play_id in sorted(bundle.playbooks))
    connectors = "\n".join(
        "- `%s` (%s)" % (item["id"], ", ".join(sorted(item.get("scopes", []))))
        for item in bundle.connectors
    ) or "- none declared"
    lines = [
        "---",
        "name: %s" % _skill_name(manifest.id),
        "description: %s" % (manifest.description or manifest.name),
        "---",
        "",
        "# %s" % manifest.name,
        "",
        "Version %s · id `%s`%s" % (
            manifest.version, manifest.id,
            " · by %s" % manifest.author if manifest.author else "",
        ),
        "",
        manifest.description,
        "",
        "## Non-negotiables",
        "",
        "1. Use the customer's connectors. Never ask for credentials or endpoints.",
        "2. Call `agents.list`, then `play.describe`, then `play.plan` before any run.",
        "3. Show the plan to a human and obtain approval for every gated step.",
        "4. Fail closed. A denial stops the run; do not work around it.",
        "5. Never put customer content in the audit trail.",
        "",
        "## Playbooks in this agent",
        "",
        plays or "- none declared",
        "",
        "## Connectors this agent may use",
        "",
        connectors,
        "",
        "## Operating pattern",
        "",
        "```",
        "agents.list -> play.describe -> play.plan",
        "           -> human approval -> play.run -> audit.explain",
        "```",
        "",
        "Run `fda serve` from this bundle or point your MCP client at "
        "`python3 -m fda`. Playbook and connector ids are namespaced with "
        "`%s` so they cannot collide with other agents." % bundle.prefix,
        "",
    ]
    return "\n".join(lines)


def export_skill(bundle: Bundle, output, prefer_custom: bool = True) -> Path:
    """Write the bundle's skill markdown to ``output``."""
    destination = Path(output)
    if destination.is_dir() or not destination.suffix:
        destination = destination / ("%s.md" % _skill_name(bundle.manifest.id))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(bundle_skill_text(bundle, prefer_custom), encoding="utf-8")
    return destination
