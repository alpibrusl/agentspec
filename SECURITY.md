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
  header, validated against `AGENTSPEC_API_KEY` using
  `secrets.compare_digest`. 401 on mismatch, 503 when the server-side
  key is unset (so a misconfigured server cannot silently accept
  unauthenticated writes).
- For local-only dev work, `AGENTSPEC_ALLOW_UNAUTHENTICATED=1` skips the
  check and logs a warning. Do not set this in production.
- Read routes (`GET /healthz`, `GET /v1/agents`, `GET /v1/agents/{ref}`)
  are public.
- The server does no authorization beyond the shared-secret check — any
  holder of `AGENTSPEC_API_KEY` can push or delete any manifest. Run a
  dedicated key per publisher if you need per-actor isolation.

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

### What AgentSpec does **not** do

- It does not sandbox the spawned CLI. The subprocess runs with the
  privileges of the invoking user.
- It does not verify that a manifest's declared `runtime` or `model`
  will behave as stated — choosing a runtime is the spec's job, not
  proving the runtime is honest.
- It does not audit MCP servers. Well-known servers in the bundled
  registry come from published upstreams; review `WELL_KNOWN_MCP_SERVERS`
  before relying on any entry.
