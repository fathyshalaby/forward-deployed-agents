# Security and trust model

## Threat model

The agent is untrusted code from the model's perspective. It receives a tool
catalog, playbooks from a bundle, and JSON results. It must never see
credentials, endpoints, free-text payloads it did not request, or another
tenant's context. The customer owns the connectors and the boundary.

## Enforced controls

| Control | Where | Behaviour |
|---|---|---|
| Declarative bundles only | `bundle.py` | Python, executables, symlinks, traversal paths and oversized files are rejected on build/install |
| Namespacing | `bundle.py` | Every playbook, connector and action id is prefixed with `<bundle id>::` |
| Scope and data-class gate | `privacy.py` | `read`/`write`/`identify`/`content` scopes checked on every call; unknown classes deny |
| Approval binding | `privacy.py`, `store.py` | Single-use, bound to action, purpose, data classes, actor, playbook hash and argument hash; optional TTL |
| Out-of-band decisions | `approval_ui.py` | Model-side `approval.grant` fails in `external` mode; approver token is separate |
| Signature and registry | `security.py` | HMAC-SHA256 over canonical file hashes; untrusted or altered bundles are rejected when required |
| Pinning | `store.py`, `runtime.py` | A pinned content hash mismatch fails closed at startup |
| Revocation | `store.py`, `security.py` | Durable and registry revocations skip or reject a bundle |
| Kill switch | `store.py`, `plays.py` | Global or per-tenant pause denies runs before any connector call |
| Content-free audit | `privacy.py`, `store.py` | Free text stored as hash; emails/tokens redacted; SHA-256 hash chain |
| Tenant/actor identity | `runtime.py`, `plays.py` | Plan and run context recorded on every audit entry |

## Signing: what it does and does not give you

`fda keys generate` creates an HMAC secret. `fda keys trust` copies that secret
into a local trust store. `agents build --sign` writes `signature.json`
containing hashes of every packaged file plus an HMAC over the canonical set.
At install, `Verifier` recomputes the HMAC with the trusted key and checks every
file hash.

This gives:

- detection of tampering in transit or on disk;
- explicit publisher allow-listing;
- deterministic content hashes suitable for pinning.

This does **not** give:

- non-repudiation — the verifier holds the same secret as the signer;
- public verification by parties who do not hold the key;
- certificate expiry, identity proof or a transparency log.

Protect the trust store like a private key (`chmod 600`, restricted volume, no
backup in a public bucket). For a public marketplace, replace the HMAC signer
with Ed25519/Sigstore-style signatures and a transparency log; the verifier
interface in `security.py` is deliberately small so that swap is local.

## Audit integrity

Each audit entry stores `prev_hash` and `hash = sha256(canonical(entry) +
prev_hash)`. `fda ops audit-verify` walks the chain and reports broken sequence
numbers. This detects edits or deletions inside the database. It cannot detect
an attacker with write access who recomputes the chain, so in production ship
entries to a write-only/WORM sink and verify there independently.

## Operational trust boundaries

- **Bundle author**: may declare descriptors and playbooks, never code or secrets.
- **Publisher**: signs a bundle; identity is the key id in the trust store.
- **Operator**: owns connectors, keys, registry, state database and approval UI.
- **Model**: can plan and run, read audit and status, but cannot grant approvals
  in `external` mode and cannot read connector credentials.
- **Approver**: holds a token for the approval UI and is attributable by name.

## Known limitations

- Simulated connectors return generic results until a real handler is registered.
- The approval UI uses a bearer token over loopback HTTP; put TLS and SSO in
  front of it before exposing it beyond localhost.
- Revocation prevents *new* loads; an already-running server must be restarted.
- Pinned bundle edits are detected at startup, not continuously.
- No sandboxing of operator handlers: treat registered adapters as trusted code.
