"""Command line: scaffold, sign, publish, install, approve and operate agents."""
import argparse
import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path

from . import __version__
from .approval_ui import serve as serve_approvals
from .bundle import (
    MANIFEST_FILE, BundleError, build_bundle, bundle_skill_text, default_store,
    export_skill, install_bundle, list_installed, load_bundle_dir,
    uninstall_bundle, validate_bundle_dir,
)
from .http_api import serve as serve_api
from .mcp import stdio_loop
from .runtime import (
    default_approval_mode, default_audit_path, default_state_path, examples_present,
    load_agents_runtime, load_runtime,
)
from .security import (
    Keyring, Registry, Signer, Verifier, default_signing_key_path,
    generate_key, read_key, sha256_file,
)
from .sdk import Client, Config
from .store import StateStore

SCAFFOLD_MANIFEST = {
    "schema": "fda-agent/v1",
    "version": "0.1.0",
    "tags": ["custom"],
    "entry": {
        "playbooks": "playbooks",
        "connectors": "connectors.json",
        "skill": "skill/SKILL.md",
    },
    "requires": {"fda": ">=0.3"},
}

SCAFFOLD_CONNECTORS = [
    {
        "id": "example",
        "name": "Example system",
        "scopes": ["read"],
        "actions": ["example.status"],
        "approval_required": [],
        "description": "A harmless demo capability; replace with a real adapter.",
    }
]

SCAFFOLD_PLAYBOOK = {
    "id": "hello",
    "name": "Hello world",
    "description": "Minimal play to prove the bundle runs end to end.",
    "purpose": "demonstrate a custom agent",
    "tags": ["example"],
    "steps": [
        {
            "id": "check",
            "title": "Read an aggregate status signal",
            "tool": "connectors.call",
            "connector": "example",
            "action": "example.status",
            "scopes": ["read"],
            "needs": ["aggregate"],
        },
        {
            "id": "handoff",
            "title": "Record a content-free handoff note",
            "tool": "note",
            "needs": ["metadata"],
        },
    ],
}


def _dump(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _fail(message: str) -> int:
    print("error: %s" % message, file=sys.stderr)
    return 1


def _store_of(args) -> Path:
    return Path(args.store) if getattr(args, "store", None) else default_store()


def _state_of(args=None) -> StateStore:
    path = getattr(args, "state", None) if args else None
    return StateStore(path or default_state_path())


def _keyring_of(args=None) -> Keyring:
    path = getattr(args, "trust", None) if args else None
    return Keyring(path)


def _verifier_of(args=None, require=None):
    keyring = _keyring_of(args)
    return Verifier(keyring) if require is None else Verifier(keyring, require=require)


def _registry_of(args=None):
    path = getattr(args, "registry", None) if args else None
    return Registry(path) if isinstance(path, str) else Registry()


def cmd_serve(args) -> int:
    if args.single:
        runtime = load_runtime(audit_path=args.audit)
    else:
        runtime = load_agents_runtime(
            store=_store_of(args),
            include_examples=not args.no_examples,
            audit_path=args.audit,
            state_path=args.state,
            approval_mode=args.approval_mode,
            tenant=args.tenant,
            actor=args.actor,
        )
    if args.approval_mode:
        runtime.approval_mode = args.approval_mode
    return stdio_loop(runtime)


def cmd_doctor(args) -> int:
    store = _store_of(args)
    state = _state_of(args)
    kill = state.kill_check(args.tenant or "")
    _dump({
        "version": __version__,
        "python": sys.version.split()[0],
        "agent_store": str(store),
        "installed_agents": [row["id"] for row in list_installed(store)],
        "approval_mode": args.approval_mode or default_approval_mode(),
        "state": str(state.path),
        "default_audit": str(default_audit_path()),
        "kill_switch": kill,
        "signature_required": _keyring_of(args).require(),
        "trusted_keys": [row["key_id"] for row in _keyring_of(args).list()],
        "env": {
            "FDA_AGENTS": os.environ.get("FDA_AGENTS", str(store)),
            "FDA_STATE": os.environ.get("FDA_STATE", str(state.path)),
            "FDA_APPROVAL_MODE": os.environ.get(
                "FDA_APPROVAL_MODE", default_approval_mode()),
            "FDA_TENANT": os.environ.get("FDA_TENANT", ""),
            "FDA_PLAYBOOKS": os.environ.get(
                "FDA_PLAYBOOKS", "checkout examples" if examples_present() else "unset"),
            "FDA_CONNECTORS": os.environ.get(
                "FDA_CONNECTORS", "checkout examples" if examples_present() else "unset"),
            "FDA_AUDIT": os.environ.get("FDA_AUDIT", str(default_audit_path())),
        },
    })
    return 0


def cmd_init(args) -> int:
    root = Path(args.directory)
    if root.exists() and any(root.iterdir()) and not args.force:
        return _fail("directory is not empty: %s (use --force)" % root)
    identifier = args.id or root.name
    manifest = dict(SCAFFOLD_MANIFEST)
    manifest.update({
        "id": identifier,
        "name": args.name or identifier,
        "description": args.description or "Describe what this agent does.",
    })
    (root / "playbooks").mkdir(parents=True, exist_ok=True)
    (root / "skill").mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "connectors.json").write_text(
        json.dumps(SCAFFOLD_CONNECTORS, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (root / "playbooks" / "hello.json").write_text(
        json.dumps(SCAFFOLD_PLAYBOOK, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    bundle = load_bundle_dir(root)
    (root / "skill" / "SKILL.md").write_text(
        bundle_skill_text(bundle, prefer_custom=False), encoding="utf-8")
    print("created agent bundle at %s" % root)
    print("next: python3 -m fda agents validate %s" % root)
    return 0


def cmd_validate(args) -> int:
    try:
        _dump(validate_bundle_dir(args.directory))
    except BundleError as exc:
        return _fail(str(exc))
    return 0


def cmd_build(args) -> int:
    signer = None
    if args.sign:
        try:
            key = read_key(args.sign)
            signer = Signer(key["key_id"], key["secret"])
        except (OSError, ValueError, KeyError) as exc:
            return _fail(str(exc))
    try:
        destination = build_bundle(args.directory, args.output, signer=signer)
    except BundleError as exc:
        return _fail(str(exc))
    _dump({"archive": str(destination), "sha256": sha256_file(destination),
           "signed": bool(signer),
           "install": "python3 -m fda agents install %s" % destination})
    return 0


def cmd_install(args) -> int:
    verifier = (_verifier_of(args, require=True)
                if (args.verify or _keyring_of(args).require()) else None)
    registry = _registry_of(args) if args.registry_check else None
    try:
        bundle = install_bundle(
            args.archive, store=_store_of(args), force=args.force,
            verifier=verifier, registry=registry, state=_state_of(args),
            pin=args.pin,
        )
    except (BundleError, ValueError) as exc:
        return _fail(str(exc))
    _dump(bundle.public())
    return 0


def cmd_list(args) -> int:
    rows = list_installed(_store_of(args))
    if args.json:
        _dump(rows)
        return 0
    if not rows:
        print("no agents installed")
        return 0
    print("%-28s %-10s %s" % ("ID", "VERSION", "NAME"))
    for row in rows:
        print("%-28s %-10s %s" % (
            row.get("id", "?"), row.get("version", "?"), row.get("name", "?")))
    return 0


def _bundle_of(args):
    return load_bundle_dir(_store_of(args) / args.agent_id)


def cmd_describe(args) -> int:
    try:
        _dump(_bundle_of(args).public())
    except BundleError as exc:
        return _fail(str(exc))
    return 0


def cmd_uninstall(args) -> int:
    removed = uninstall_bundle(args.agent_id, store=_store_of(args))
    if not removed:
        return _fail("agent not installed: %s" % args.agent_id)
    _state_of(args).unpin(args.agent_id)
    print("uninstalled %s" % args.agent_id)
    return 0


def cmd_skill(args) -> int:
    try:
        bundle = _bundle_of(args)
    except BundleError as exc:
        return _fail(str(exc))
    if args.output:
        destination = export_skill(bundle, args.output,
                                   prefer_custom=not args.generated)
        print("wrote %s" % destination)
        return 0
    if args.target:
        name = bundle.manifest.id.replace(".", "-").replace("::", "-")
        base = Path.cwd() / (".opencode" if args.target == "opencode" else ".claude")
        destination = export_skill(
            bundle, base / "skills" / name / "SKILL.md",
            prefer_custom=not args.generated,
        )
        print("wrote %s" % destination)
        return 0
    print(bundle_skill_text(bundle, prefer_custom=not args.generated))
    return 0


def cmd_pin(args) -> int:
    from .security import content_hash
    bundle = _bundle_of(args)
    fingerprint = content_hash(bundle.root)
    _state_of(args).pin(bundle.manifest.id, fingerprint)
    _dump({"agent": bundle.manifest.id, "content_hash": fingerprint})
    return 0


def cmd_unpin(args) -> int:
    _state_of(args).unpin(args.agent_id)
    print("unpinned %s" % args.agent_id)
    return 0


# --------------------------------------------------------------------- keys
def cmd_keys_generate(args) -> int:
    key = generate_key(args.key_id, args.publisher, args.output)
    _dump({**key, "secret": "[stored in %s]" % (args.output or default_signing_key_path())})
    return 0


def cmd_keys_trust(args) -> int:
    keyring = _keyring_of(args)
    keyring.add(read_key(args.keyfile))
    print("trusted %s" % read_key(args.keyfile)["key_id"])
    return 0


def cmd_keys_list(args) -> int:
    _dump({"required": _keyring_of(args).require(),
           "keys": _keyring_of(args).list()})
    return 0


def cmd_keys_require(args) -> int:
    enabled = args.enabled == "on" if isinstance(args.enabled, str) else args.enabled
    _keyring_of(args).set_required(enabled)
    print("signature required: %s" % enabled)
    return 0


# ----------------------------------------------------------------- registry
def cmd_registry_init(args) -> int:
    _dump(_registry_of(args).init())
    return 0


def cmd_registry_publish(args) -> int:
    keyring = _keyring_of(args)
    key = read_key(args.keyfile) if args.keyfile else None
    verifier = (Verifier(keyring, require=True)
                if (args.verify or keyring.require()) else None)
    _dump(_registry_of(args).publish(
        args.archive, verifier=verifier,
        key_id=key["key_id"] if key else "",
        publisher=key.get("publisher", "") if key else "",
    ))
    return 0


def cmd_registry_list(args) -> int:
    _dump({"entries": _registry_of(args).list(),
           "revocations": _registry_of(args).revoked()})
    return 0


def cmd_registry_revoke(args) -> int:
    _dump(_registry_of(args).revoke(args.agent_id, args.version, args.reason))
    return 0


# ---------------------------------------------------------------- approvals
def cmd_approvals_list(args) -> int:
    _dump({"approvals": _state_of(args).approval_list(args.status, args.limit)})
    return 0


def cmd_approvals_grant(args) -> int:
    ok, status = _state_of(args).approval_decide(args.approval_id, "grant",
                                                 args.approver)
    if not ok:
        return _fail(status)
    _dump({"approval_id": args.approval_id, "status": status,
           "approver": args.approver})
    return 0


def cmd_approvals_deny(args) -> int:
    ok, status = _state_of(args).approval_decide(args.approval_id, "deny",
                                                 args.approver)
    if not ok:
        return _fail(status)
    _dump({"approval_id": args.approval_id, "status": status,
           "approver": args.approver})
    return 0


def cmd_approvals_serve(args) -> int:
    if not args.token:
        return _fail("--token is required (a long random string shared with approvers)")
    server = serve_approvals(args.state, args.token, args.host, args.port)
    print("approval UI on http://%s:%d (token required)" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------------- ops
def cmd_ops_status(args) -> int:
    state = _state_of(args)
    _dump({"kill_switch": state.kill_status(), "stats": state.stats(),
           "audit_chain": state.audit_verify()})
    return 0


def cmd_ops_pause(args) -> int:
    _state_of(args).kill_set(args.scope, True, args.reason)
    print("paused %s" % args.scope)
    return 0


def cmd_ops_resume(args) -> int:
    _state_of(args).kill_set(args.scope, False, "")
    print("resumed %s" % args.scope)
    return 0


def cmd_ops_revoke(args) -> int:
    _state_of(args).revoke(args.agent_id, args.version, args.reason)
    print("revoked %s %s" % (args.agent_id, args.version))
    return 0


def cmd_ops_audit_verify(args) -> int:
    result = _state_of(args).audit_verify()
    _dump(result)
    return 0 if result["ok"] else 1


def cmd_api_serve(args) -> int:
    config = Config(
        state_path=args.state,
        store=args.store,
        audit_path=args.audit,
        persist_audit=not args.no_state,
        approval_mode=args.approval_mode,
        tenant=args.tenant,
        actor=args.actor,
        include_examples=not args.no_examples,
    )
    client = Client.create(config)
    token = args.token or os.environ.get("FDA_API_TOKEN", "")
    print("FDA JSON API on http://%s:%d/v1" % (args.host, args.port))
    serve_api(client, args.host, args.port, token, args.allow_origin)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fda", description="Forward-deployed agents: build, share, run and operate agents.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP stdio server (default)")
    serve.add_argument("--store")
    serve.add_argument("--no-examples", action="store_true")
    serve.add_argument("--audit")
    serve.add_argument("--state")
    serve.add_argument("--approval-mode", choices=("demo", "external"))
    serve.add_argument("--tenant")
    serve.add_argument("--actor")
    serve.add_argument("--single", action="store_true")
    serve.set_defaults(func=cmd_serve)

    doctor = sub.add_parser("doctor", help="show deployment configuration")
    doctor.add_argument("--store")
    doctor.add_argument("--state")
    doctor.add_argument("--trust")
    doctor.add_argument("--tenant")
    doctor.add_argument("--approval-mode", choices=("demo", "external"))
    doctor.set_defaults(func=cmd_doctor)

    agents = sub.add_parser("agents", help="create, package and install agent bundles")
    agent_sub = agents.add_subparsers(dest="agent_command", required=True)

    def with_store(command_parser):
        command_parser.add_argument("--store")
        return command_parser

    def with_state(command_parser):
        command_parser.add_argument("--state")
        return command_parser

    init = agent_sub.add_parser("init", help="scaffold a new agent bundle")
    init.add_argument("directory")
    init.add_argument("--id")
    init.add_argument("--name")
    init.add_argument("--description")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    validate = agent_sub.add_parser("validate", help="validate a bundle directory")
    validate.add_argument("directory")
    validate.set_defaults(func=cmd_validate)

    build = agent_sub.add_parser("build", help="package a bundle into a .fda archive")
    build.add_argument("directory")
    build.add_argument("-o", "--output")
    build.add_argument("--sign", help="sign with this key file (see `fda keys generate`)")
    build.set_defaults(func=cmd_build)

    install = with_state(with_store(
        agent_sub.add_parser("install", help="install a .fda archive")))
    install.add_argument("archive")
    install.add_argument("--force", action="store_true")
    install.add_argument("--verify", action="store_true", help="require a trusted signature")
    install.add_argument("--registry-check", action="store_true",
                         help="require a matching registry entry")
    install.add_argument("--registry")
    install.add_argument("--trust")
    install.add_argument("--pin", action="store_true", help="pin this content hash")
    install.set_defaults(func=cmd_install)

    listing = with_store(agent_sub.add_parser("list", help="list installed agents"))
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    describe = with_store(agent_sub.add_parser("describe", help="describe one agent"))
    describe.add_argument("agent_id")
    describe.set_defaults(func=cmd_describe)

    uninstall = with_state(with_store(
        agent_sub.add_parser("uninstall", help="remove an agent")))
    uninstall.add_argument("agent_id")
    uninstall.set_defaults(func=cmd_uninstall)

    skill = with_store(agent_sub.add_parser("skill", help="export an AI skill"))
    skill.add_argument("agent_id")
    skill.add_argument("-o", "--output")
    skill.add_argument("--target", choices=("opencode", "claude"))
    skill.add_argument("--generated", action="store_true")
    skill.set_defaults(func=cmd_skill)

    pin = with_state(with_store(agent_sub.add_parser("pin", help="pin a bundle hash")))
    pin.add_argument("agent_id")
    pin.set_defaults(func=cmd_pin)

    unpin = with_state(agent_sub.add_parser("unpin", help="remove a bundle pin"))
    unpin.add_argument("agent_id")
    unpin.set_defaults(func=cmd_unpin)

    keys = sub.add_parser("keys", help="publisher keys and trust store")
    key_sub = keys.add_subparsers(dest="key_command", required=True)

    generate = key_sub.add_parser("generate", help="create a signing key")
    generate.add_argument("--key-id", required=True)
    generate.add_argument("--publisher", required=True)
    generate.add_argument("-o", "--output")
    generate.set_defaults(func=cmd_keys_generate)

    trust = key_sub.add_parser("trust", help="trust a publisher key")
    trust.add_argument("keyfile")
    trust.add_argument("--trust")
    trust.set_defaults(func=cmd_keys_trust)

    key_list = key_sub.add_parser("list", help="list trusted keys")
    key_list.add_argument("--trust")
    key_list.set_defaults(func=cmd_keys_list)

    require = key_sub.add_parser("require", help="require signatures on install")
    require.add_argument("enabled", choices=("on", "off"))
    require.add_argument("--trust")
    require.set_defaults(func=cmd_keys_require)

    registry = sub.add_parser("registry", help="publish and revoke agent bundles")
    registry_sub = registry.add_subparsers(dest="registry_command", required=True)

    reg_init = registry_sub.add_parser("init", help="initialise a local registry")
    reg_init.add_argument("--registry")
    reg_init.set_defaults(func=cmd_registry_init)

    publish = registry_sub.add_parser("publish", help="publish an archive")
    publish.add_argument("archive")
    publish.add_argument("--registry")
    publish.add_argument("--trust")
    publish.add_argument("--keyfile")
    publish.add_argument("--verify", action="store_true")
    publish.set_defaults(func=cmd_registry_publish)

    reg_list = registry_sub.add_parser("list", help="list registry entries")
    reg_list.add_argument("--registry")
    reg_list.set_defaults(func=cmd_registry_list)

    revoke_reg = registry_sub.add_parser("revoke", help="revoke a published version")
    revoke_reg.add_argument("agent_id")
    revoke_reg.add_argument("--version", default="*")
    revoke_reg.add_argument("--reason", default="")
    revoke_reg.add_argument("--registry")
    revoke_reg.set_defaults(func=cmd_registry_revoke)

    approvals = sub.add_parser("approvals", help="out-of-band human approvals")
    approval_sub = approvals.add_subparsers(dest="approval_command", required=True)

    app_list = with_state(approval_sub.add_parser("list", help="list approval requests"))
    app_list.add_argument("--status", choices=("pending", "granted", "denied"))
    app_list.add_argument("--limit", type=int, default=50)
    app_list.set_defaults(func=cmd_approvals_list)

    grant = with_state(approval_sub.add_parser("grant", help="grant an approval"))
    grant.add_argument("approval_id")
    grant.add_argument("--approver", required=True)
    grant.set_defaults(func=cmd_approvals_grant)

    deny = with_state(approval_sub.add_parser("deny", help="deny an approval"))
    deny.add_argument("approval_id")
    deny.add_argument("--approver", required=True)
    deny.set_defaults(func=cmd_approvals_deny)

    app_serve = with_state(approval_sub.add_parser("serve", help="run the approval UI"))
    app_serve.add_argument("--token", default=os.environ.get("FDA_APPROVER_TOKEN", ""))
    app_serve.add_argument("--host", default="127.0.0.1")
    app_serve.add_argument("--port", type=int, default=8787)
    app_serve.set_defaults(func=cmd_approvals_serve)

    ops = sub.add_parser("ops", help="kill switch, revocation and audit health")
    ops_sub = ops.add_subparsers(dest="ops_command", required=True)

    op_status = with_state(ops_sub.add_parser("status", help="show operational state"))
    op_status.set_defaults(func=cmd_ops_status)

    pause = with_state(ops_sub.add_parser("pause", help="pause runs"))
    pause.add_argument("--scope", default="*", help="tenant id or * for all")
    pause.add_argument("--reason", default="")
    pause.set_defaults(func=cmd_ops_pause)

    resume = with_state(ops_sub.add_parser("resume", help="resume runs"))
    resume.add_argument("--scope", default="*")
    resume.set_defaults(func=cmd_ops_resume)

    revoke = with_state(ops_sub.add_parser("revoke", help="revoke an installed bundle"))
    revoke.add_argument("agent_id")
    revoke.add_argument("--version", default="*")
    revoke.add_argument("--reason", default="")
    revoke.set_defaults(func=cmd_ops_revoke)

    verify = with_state(ops_sub.add_parser("audit-verify", help="verify audit hash chain"))
    verify.set_defaults(func=cmd_ops_audit_verify)

    api = sub.add_parser("api", help="embed the agent runtime over JSON HTTP")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_serve = api_sub.add_parser("serve", help="run the JSON API server")
    api_serve.add_argument("--host", default="127.0.0.1")
    api_serve.add_argument("--port", type=int, default=8080)
    api_serve.add_argument("--token", default=os.environ.get("FDA_API_TOKEN", ""))
    api_serve.add_argument("--allow-origin", default="")
    api_serve.add_argument("--store")
    api_serve.add_argument("--state")
    api_serve.add_argument("--audit")
    api_serve.add_argument("--tenant")
    api_serve.add_argument("--actor")
    api_serve.add_argument("--approval-mode", choices=("demo", "external"))
    api_serve.add_argument("--no-state", action="store_true",
                           help="in-memory demo mode")
    api_serve.add_argument("--no-examples", action="store_true")
    api_serve.set_defaults(func=cmd_api_serve)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return stdio_loop(load_agents_runtime())
    try:
        return args.func(args)
    except (BundleError, OSError, ValueError) as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
