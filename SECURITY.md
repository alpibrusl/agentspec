# Security Policy

## Reporting a Vulnerability

Private disclosure via GitHub Security Advisories on
<https://github.com/alpibrusl/agentspec> or email to
`security@alpibru.com`. Do not open a public issue.

Include: description, steps to reproduce, affected version, PoC if any.

## Supported Versions

| Version | Status |
|---------|--------|
| 0.4.x   | Active — security fixes backported |
| < 0.4   | Not supported |

## Trust Model

AgentSpec processes two inputs that flow through security-relevant paths:
**agent manifests** (`.agent` YAML) and **signed agent profiles**. The rest
of this document describes what each subsystem does and does not protect
against.

### Manifest parsing

- `.agent` files are parsed with `yaml.safe_load` — no arbitrary Python
  execution from a malicious manifest.
- The inheritance merger (`agentspec.resolver.merger`) enforces the
  `trust: restrict` invariant: child trust levels are always pinned to
  the more-restrictive of (parent, child) across filesystem, network, and
  exec dimensions. A child cannot widen the parent's trust, only narrow it.
- The resolver does not execute any code from the manifest; it only
  chooses a runtime and environment based on the declared tools/skills.

### Profile signing

- Signing uses Ed25519 via PyNaCl (hard dep; HMAC fallback was removed
  in 0.4.0). `generate_keypair()` and `public_key_for(private_key_hex)`
  produce matching values — use one or the other, never `sha256(privkey)`.
- `verify_memory`, `verify_portfolio_entry`, `verify_skill_proof`
  validate against the canonical JSON payload and reject envelopes whose
  `algorithm` is anything other than `ed25519`.
- The 15 tests in `tests/test_signing.py` cover round-trip, tamper,
  wrong-key, malformed-signature, unknown-algorithm, and pubkey-consistency
  regressions. Treat any failure in those tests as a hard release blocker.
- **Signing proves who signed a payload and that the bytes have not been
  tampered with.** It does not prove the referenced agent actually
  accomplished what a portfolio entry claims.

### Registry server (`agentspec.registry.server`)

- `POST /v1/agents` and `DELETE /v1/agents/{ref}` require the `X-API-Key`
  header, validated with `secrets.compare_digest`. 401 on mismatch, 503
  when no keys are configured at all (so a misconfigured server cannot
  silently accept unauthenticated writes).
- **Multi-tenant auth** (recommended): set
  `AGENTSPEC_API_KEYS="alice:k1,bob:k2"`. The portion before the first
  colon is the tenant ID; the remainder is the API key. Each tenant is
  isolated at the storage layer — `alice` cannot pull, list, or delete
  `bob`'s manifests when authenticated. Cross-tenant access surfaces as
  `404`, not `403`, so callers cannot probe for the existence of other
  tenants' manifests.
- **Legacy single-tenant auth**: set `AGENTSPEC_API_KEY="secret"`. The
  key is mapped to the tenant name `default`. When both env vars are
  set, `AGENTSPEC_API_KEYS` wins — the legacy key stops working.
- For local-only dev work, `AGENTSPEC_ALLOW_UNAUTHENTICATED=1` skips
  the check and writes land in the `default` tenant. Do not set this in
  production.
- Read routes (`GET /healthz`, `GET /v1/agents`, `GET /v1/agents/{ref}`)
  stay public: anonymous callers see the aggregated catalog across all
  tenants (backwards-compatible). An authenticated read is scoped to
  the caller's tenant.
- Tenant IDs in `AGENTSPEC_API_KEYS` control storage directory names
  (`{base}/tenants/{tenant}/`). Avoid path-traversal characters
  (`/`, `..`) in tenant IDs.

### Registry client (`agentspec.registry.client`)

- Reads `AGENTSPEC_API_KEY` (or `NOETHER_API_KEY` as a fallback) from
  env. Passes it via `X-API-Key`; never logs or persists the value.

### Runner (`agentspec.runner`)

- Materialises `.agent` content into the config files each target CLI
  reads natively (`CLAUDE.md`, `GEMINI.md`, `.cursorrules`,
  `.mcp.json`, etc.) via `provision()` and optionally registers MCP
  servers via `provision_install()`.
- `provision_install()` will invoke `pip install`, `npm install`, and
  arbitrary setup commands declared in the manifest. Treat manifests
  as executable inputs — do not provision manifests from untrusted
  sources on a host you are not willing to lose.

### Runner isolation (`agentspec.runner.isolation`)

- The runner wraps the spawned CLI in bubblewrap (`bwrap`) when
  available, deriving the sandbox policy from the manifest's
  `TrustSpec` (filesystem / network / exec axes). Fresh namespaces,
  `--cap-drop ALL`, `--die-with-parent`, `--clearenv` with an
  allowlist, `/nix/store`-style RO binds, workdir-only RW by default.
- `--via auto` (default) picks bwrap when installed; falls back to
  running unsandboxed on a fully permissive manifest with a warning;
  **raises** on a non-trivial trust manifest when bwrap is missing
  (no silent downgrade).
- `--via bwrap` requires bwrap; fail fast if missing.
- `--via none --unsafe-no-isolation` is the explicit opt-out.
  `AGENTSPEC_ISOLATION=auto|bwrap|none` is the env fallback.
- Phase 1 is bwrap. It does not block `execve` by itself —
  `trust.exec: none` is enforced by cap-drop + the bind-mount set (no
  path to an arbitrary binary), not by seccomp. Phase 2 (native
  namespaces + Landlock + seccomp) is planned in agentspec Proposal
  002 and waits on either native implementation or delegation to
  noether's [future run-external](https://github.com/alpibrusl/noether/issues/36).
- Per-URL network allowlisting is not implemented. `trust.network:
  scoped` degrades to `allowed` with a resolver warning. Closing this
  is a Phase 2 item.
- On macOS / Windows, bwrap is unavailable; `--via auto` falls back to
  `NONE` with a platform warning. Tight-trust manifests on those
  platforms raise unless `--unsafe-no-isolation` is set.

### What AgentSpec does **not** do

- It does not verify that a manifest's declared `runtime` or `model`
  will behave as stated — choosing a runtime is the spec's job, not
  proving the runtime is honest.
- It does not audit MCP servers. Well-known servers in the bundled
  registry come from published upstreams; review `WELL_KNOWN_MCP_SERVERS`
  before relying on any entry.
- It does not prevent a sandboxed runtime from *generating* harmful
  text and sending it back to you. The sandbox is process-level; it
  does not filter model output. Output filtering / tool-call
  allowlists are a separate concern upstream of the runner.
