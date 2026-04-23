---
name: agentspec
description: Resolve and run AI agent manifests (.agent files) across multiple LLM runtimes. Manifests declare persona, skills, trust, model preferences; agentspec picks a concrete runtime + model from the environment.
when_to_use: Use when the user has a .agent manifest or wants to validate, resolve, run, lock, or publish one. Do not reach for agentspec to invoke an LLM directly — the runtimes agentspec spawns (claude-code, gemini-cli, etc.) remain the right tool for that.
---

# agentspec

> Auto-generated skill file for `agentspec` v0.1.0
> Re-generate with: `agentspec skill` or `acli skill --bin agentspec`

## Available commands

- `agentspec run` — Resolve and run an agent from a .agent file or directory.
- `agentspec validate` — Validate a .agent file or directory against the schema. (idempotent)
- `agentspec resolve` — Show what would run without executing. Always verbose. (idempotent)
- `agentspec extend` — Scaffold a new agent that extends an existing one.
- `agentspec push` — Publish an agent to a registry (local or remote Noether registry). (idempotent)
- `agentspec pull` — Pull an agent from a registry (local or remote Noether registry). (idempotent)
- `agentspec search` — Search for agents in a remote Noether registry. (idempotent)
- `agentspec schema` — Print the JSON Schema for .agent files. (idempotent)
- `agentspec init` — Scaffold a new .agent project.
- `agentspec lock` — Pin a manifest's resolved plan to a lockfile. (idempotent)
- `agentspec verify-lock` — Verify a signed lockfile against a public key. (idempotent)
- `agentspec gym` — Tune and test agents against task fixtures in isolation
- `agentspec records` — Inspect and verify execution records written by agentspec run

## `agentspec run`

Resolve and run an agent from a .agent file or directory.

### Options

- `--input-` (string) — Input to pass to the agent. type:string [default: ]
- `--verbose` (bool) — Show resolver decisions. type:bool [default: False]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]
- `--dry-run` (bool) — Resolve without executing. type:bool [default: False]
- `--via` (string) — Isolation backend: auto|bwrap|none. Defaults to auto (use bwrap if installed). Reads AGENTSPEC_ISOLATION env if unset. type:string [default: ]
- `--unsafe-no-isolation` (bool) — Acknowledge running a tight-trust manifest without a sandbox. Required with --via=none on non-permissive manifests. type:bool [default: False]
- `--lock` (string) — Path to an agentspec.lock file. Skips resolve and uses the pinned plan; the manifest's hash must match the lock. type:path [default: ]
- `--require-signed` (bool) — Refuse to run unless --lock is a signed envelope that verifies against --pubkey. Pair with --pubkey <hex>. type:bool [default: False]
- `--pubkey` (string) — Ed25519 public key (hex) to verify --lock against when --require-signed is set. type:string [default: ]

### Arguments

- `agent_path` (string, required) — Path to .agent file or directory. type:path

### Examples

```bash
# Run a researcher agent
agentspec run researcher.agent
```

```bash
# Run with input
agentspec run researcher.agent --input 'quantum tunneling'
```

```bash
# Dry-run to see the plan
agentspec run researcher.agent --dry-run
```

```bash
# Verbose resolver output
agentspec run researcher.agent --verbose
```

**See also:** `agentspec resolve`, `agentspec validate`

## `agentspec validate`

Validate a .agent file or directory against the schema.

### Options

- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `agent_path` (string, required) — Path to .agent file or directory. type:path

### Examples

```bash
# Validate a single file
agentspec validate researcher.agent
```

```bash
# Validate a directory agent
agentspec validate ./researcher/
```

```bash
# JSON output
agentspec validate researcher.agent --output json
```

**See also:** `agentspec resolve`, `agentspec schema`

## `agentspec resolve`

Show what would run without executing. Always verbose.

### Options

- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `agent_path` (string, required) — Path to .agent file or directory. type:path

### Examples

```bash
# Show resolver plan
agentspec resolve researcher.agent
```

```bash
# JSON output
agentspec resolve researcher.agent --output json
```

**See also:** `agentspec run`, `agentspec validate`

## `agentspec extend`

Scaffold a new agent that extends an existing one.

### Options

- `--out` (string) — Output file path. type:path [default: extended.agent]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]
- `--dry-run` (string) — Describe actions without executing. type:bool [default: False]

### Arguments

- `base_path` (string, required) — Base agent to extend. type:path

### Examples

```bash
# Extend a researcher
agentspec extend researcher.agent
```

```bash
# Custom output file
agentspec extend researcher.agent --out legal-researcher.agent
```

**See also:** `agentspec validate`, `agentspec init`

## `agentspec push`

Publish an agent to a registry (local or remote Noether registry).

### Options

- `--registry` (string) — Remote registry URL (e.g. http://localhost:3000). Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string [default: ]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `agent_path` (string, required) — Path to .agent file or directory. type:path

### Examples

```bash
# Push to local registry
agentspec push researcher.agent
```

```bash
# Push to remote registry
agentspec push researcher.agent --registry http://localhost:3000
```

```bash
# JSON output
agentspec push researcher.agent --output json
```

**See also:** `agentspec pull`, `agentspec search`, `agentspec validate`

## `agentspec pull`

Pull an agent from a registry (local or remote Noether registry).

### Options

- `--registry` (string) — Remote registry URL. Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string [default: ]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `ref` (string, required) — Agent reference: registry stage ID or ag1:<hash>. type:string

### Examples

```bash
# Pull from local registry
agentspec pull ag1:abc123def456
```

```bash
# Pull from remote registry
agentspec pull abc123def456 --registry http://localhost:3000
```

```bash
# JSON output
agentspec pull ag1:abc123 --output json
```

**See also:** `agentspec push`, `agentspec search`

## `agentspec search`

Search for agents in a remote Noether registry.

### Options

- `--registry` (string) — Registry URL. Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string [default: ]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `query` (string, required) — Search query. type:string

### Examples

```bash
# Search for researcher agents
agentspec search researcher --registry http://localhost:3000
```

```bash
# JSON output
agentspec search coder --registry http://localhost:3000 --output json
```

**See also:** `agentspec push`, `agentspec pull`

## `agentspec schema`

Print the JSON Schema for .agent files.

### Options

- `--out` (string) — Write schema to file. type:path [default: ]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Examples

```bash
# Print JSON Schema
agentspec schema
```

```bash
# Save to file
agentspec schema --out agent-v1.json
```

**See also:** `agentspec validate`

## `agentspec init`

Scaffold a new .agent project.

### Options

- `--format-` (string) — Format: file or directory. type:enum[file|directory] [default: file]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]
- `--dry-run` (string) — Describe actions without executing. type:bool [default: False]

### Arguments

- `name` (string, required) — Agent name. type:string

### Examples

```bash
# Create a new agent
agentspec init my-agent
```

```bash
# Create directory format
agentspec init my-agent --format directory
```

**See also:** `agentspec extend`, `agentspec validate`

## `agentspec lock`

Pin a manifest's resolved plan to a lockfile.

### Options

- `--out` (string) — Output path. Defaults to <agent_path>.lock. type:path [default: ]
- `--sign-key-env` (string) — Name of an env var holding the Ed25519 private key (hex). When set, writes a signed envelope instead of plain JSON. type:string [default: ]
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `agent_path` (string, required) — Path to .agent file or directory. type:path

### Examples

```bash
# Lock a manifest
agentspec lock researcher.agent
```

```bash
# Custom output path
agentspec lock researcher.agent --out my.lock
```

```bash
# Signed lock via env-held key
AGENTSPEC_LOCK_SIGNING_KEY=<hex> agentspec lock researcher.agent --sign-key-env AGENTSPEC_LOCK_SIGNING_KEY
```

**See also:** `agentspec run`, `agentspec verify-lock`

## `agentspec verify-lock`

Verify a signed lockfile against a public key.

### Options

- `--pubkey` (string) — Ed25519 public key (hex) to verify against. type:string
- `--output` (OutputFormat) — Output format. type:enum[text|json|table] [default: text]

### Arguments

- `lock_path` (string, required) — Path to an agentspec.lock file. type:path

### Examples

```bash
# Verify a signed lock
agentspec verify-lock researcher.agent.lock --pubkey <hex>
```

```bash
# JSON output
agentspec verify-lock researcher.agent.lock --pubkey <hex> --output json
```

**See also:** `agentspec lock`, `agentspec run`

## `agentspec gym`

Tune and test agents against task fixtures in isolation

## `agentspec records`

Inspect and verify execution records written by agentspec run

## Output format

All commands support `--output json|text|table`. When using `--output json`, responses follow a standard envelope:

```json
{"ok": true, "command": "...", "data": {...}, "meta": {"duration_ms": ..., "version": "..."}}
```

Errors use the same envelope with `"ok": false` and an `"error"` object containing `code`, `message`, `hint`, and `docs`.

## Exit codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success | Proceed |
| 2 | Invalid arguments | Correct and retry |
| 3 | Not found | Check inputs |
| 5 | Conflict | Resolve conflict |
| 8 | Precondition failed | Fix precondition |
| 9 | Dry-run completed | Review and confirm |

## Further discovery

- `agentspec --help` — full help for any command
- `agentspec introspect` — machine-readable command tree (JSON)
- `.cli/README.md` — persistent reference (survives context resets)
