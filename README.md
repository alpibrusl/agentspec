# AgentSpec

**Trust-restricting inheritance for agent manifests. A resolver turns them into a runnable CLI invocation.**

[![License](https://img.shields.io/badge/License-EUPL--1.2-blue.svg)](https://eupl.eu/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-278%20passing-brightgreen.svg)](tests/)

Existing agent formats (gitagent, Agent Format, OSSA, Open Agent Spec) are static config files. AgentSpec is two things neither of them does:

1. **A trust model.** Agent manifests inherit from other manifests, and a child can only *narrow* the parent's trust — never widen it. The merger enforces the invariant across three dimensions (filesystem, network, exec) at parse time, so no downstream code path can accidentally elevate a child past its parent's permissions.
2. **A resolver.** Given a manifest and the state of your machine (CLIs installed, API keys in env, models available), it picks the concrete runtime + flags that will actually run. If the environment is short of what the manifest needs, it tells you what's missing instead of failing mid-execution.

```yaml
# parent.agent
trust:
  filesystem: readwrite
  network: allow
  exec: allow

# child.agent
inherits: parent
trust:
  filesystem: readonly     # narrowed — OK
  network: deny            # narrowed — OK
  exec: allow              # inherited
```

After merge, the child has `{readonly, deny, allow}`. If it had tried to widen any dimension (e.g. `filesystem: readwrite` in the child), the merger rejects the manifest at load time.

```
your .agent file
      ↓
  resolver + trust-restricting merger    ← the defensible bits
      ↓
claude-code / gemini-cli / codex-cli / aider / opencode / ollama
```

### Supporting features (not the pitch)

- **Agent profiles.** Persist what an agent has done across sprints. Ed25519-signed so tampering is detectable. Signing proves *who signed* the bytes — not that the claimed work actually happened. Currently alpha; don't deploy without reading [SECURITY.md](./SECURITY.md).
- **Registry.** FastAPI push/pull for agent manifests. Also alpha — read SECURITY.md before exposing.
- **Noether composition.** Optional integration for pipelines built on [Noether](https://github.com/alpibrusl/noether).

---

## Why AgentSpec

> "I have this agent definition. Don't let a child widen trust beyond its parent. Figure out what CLI is installed, what API keys I have, pick the best runtime, warn me about what's missing, and just run it."

| Feature | AgentSpec | Others |
|---|---|---|
| **Trust-restricting inheritance** (merger enforces invariant) | ✓ | ✗ |
| **Resolver** (auto-negotiate runtime) | ✓ | ✗ |
| Content-addressable hashing | ✓ | partial |
| Multi-runtime (6 frameworks) | ✓ | usually 1 |
| ACLI-compliant CLI for agent discovery | ✓ | ✗ |
| Signed portfolios (alpha) | ✓ | ✗ |
| Noether composition integration | ✓ | ✗ |

---

## Install

```bash
pip install agentspec-alpibru
```

PyNaCl ships as a core dep — signing works out of the box. Optional extras:

```bash
pip install "agentspec-alpibru[registry]"     # FastAPI registry server

# (The package is published as agentspec-alpibru on PyPI.
#  In code, you still import it as `agentspec`.)
```

---

## Quick Start

```bash
# Create a new agent
agentspec init my-researcher

# Validate the schema
agentspec validate my-researcher.agent

# See what would run (without executing)
agentspec resolve my-researcher.agent

# Run it
agentspec run my-researcher.agent --input "quantum tunneling"

# Push to a registry
agentspec push my-researcher.agent --registry https://registry.agentspec.dev

# Pull and run someone else's agent
agentspec pull ag1:abc123 --registry https://registry.agentspec.dev
```

---

## The `.agent` Format

```yaml
apiVersion: agent/v1
name: deep-researcher
version: 1.0.0

# What model + capability tier
model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b

# Abstract skills (resolver maps to concrete tools)
skills:
  - web-search
  - cite-sources

# Behavior traits (portable across models)
behavior:
  traits:
    - cite-everything
    - never-guess
  temperature: 0.2

# Trust invariant — child cannot escalate
trust:
  filesystem: none
  network: allowed
  exec: none
```

Two formats supported:

- **Single file** (`researcher.agent`) — simple, hashable
- **Directory** (`researcher/`) — rich identity with `agent.yaml` + `SOUL.md` + `RULES.md`

---

## Inheritance

Agents extend other agents with enforced merge semantics:

```yaml
base: ./researcher.agent
merge:
  skills: append      # append | override | restrict
  tools: append
  behavior: override
  trust: restrict     # always restrict — child cannot escalate
```

The `trust: restrict` invariant is **hardcoded**. A child agent can never escalate permissions beyond its parent. Enforced at merge time.

---

## The Resolver

Given a `.agent` file, the resolver:

1. Detects installed runtimes (`shutil.which("claude")`, etc.)
2. Checks API keys in environment
3. Walks the model preference list, picks the first that's available
4. Maps abstract skills to concrete tools
5. Builds the system prompt from traits / SOUL.md / RULES.md
6. Falls back to capability tier if no preferred model resolves
7. Explains every decision with `--verbose`

```bash
$ agentspec resolve researcher.agent
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    web-search, cite-sources
  Resolver decisions:
    Detected runtimes: [claude-code, gemini-cli, ollama]
      selected claude/claude-sonnet-4-6 via claude-code (env.ANTHROPIC_API_KEY)
      skill web-search: resolved to brave-mcp
      skill cite-sources: resolved to arxiv-mcp
```

---

## Agent Profiles & Signed Portfolios

**The killer feature.** Every agent gets a persistent profile that accumulates across sprints — a verifiable CV signed by the supervisor.

```python
from agentspec.profile import ProfileManager
from agentspec import load_agent

mgr = ProfileManager("./profiles")
manifest = load_agent("my-agent.agent")
profile = mgr.load_or_create(manifest)

# After a sprint completes
mgr.process_retro(profile, feedback={
    "assessment": "completed",
    "blockers": ["pandas std=0 silently skips z-score"],
    "tools": ["pandas", "fastapi", "pytest"],
    "clarity": 9,
}, sprint_id="sprint-42", project="OTA Anomaly Detector")

# Profile now has:
#   - signed memories (Ed25519)
#   - portfolio entry
#   - skill proofs (pandas at 70% confidence)
#   - all verifiable against supervisor pubkey
```

Cold start: profiles seed from the manifest (declared skills at 30%). After real sprints, demonstrated skills upgrade to 70%+.

This means agents are **portable with their experience**. Pull an agent from the registry and you get not just its config but its accumulated knowledge — signed, verifiable, content-addressed.

---

## ACLI Compliant

Built with [ACLI](https://github.com/alpibrusl/acli) — agents discover capabilities at runtime:

```bash
agentspec introspect          # full command tree as JSON
agentspec skill               # generate SKILLS.md
agentspec --help              # structured help
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `run` | Resolve and execute an agent |
| `validate` | Validate a `.agent` file against the schema |
| `resolve` | Show what would run without executing |
| `extend` | Scaffold a child agent extending an existing one |
| `push` | Publish an agent to a registry (local or Noether) |
| `pull` | Fetch an agent from a registry |
| `search` | Semantic search for agents in a registry |
| `schema` | Print the JSON Schema for `.agent` files |
| `init` | Scaffold a new `.agent` project |

---

## Noether Integration

AgentSpec operations are registered as [Noether](https://github.com/alpibrusl/noether) stages — content-addressed, type-safe, composable:

```bash
noether stage search "agentspec"

# Returns 9 stages:
#   agentspec_validate    27980442
#   agentspec_resolve     2a6da6ec
#   agentspec_hash        99640059
#   agentspec_merge       284128cf
#   agentspec_evolve      002cebee
#   agentspec_schema      7ea3d017
#   agentspec_profile_create  89146f8f
#   agentspec_profile_retro   23b7f0f1
#   agentspec_profile_export  795d38b0
```

Compose AgentSpec operations with the 370+ other Noether stages (data, AI, web, infra) and serve them as HTTP APIs via `noether serve`.

---

## Registry

Push and pull agents from any [Noether-compatible](https://github.com/alpibrusl/noether-cloud) registry:

```bash
# Self-hosted (docker compose up in noether-cloud)
agentspec push my.agent --registry http://localhost:3000

# Public registry
agentspec push my.agent --registry https://registry.agentspec.dev
agentspec search "researcher" --registry https://registry.agentspec.dev
agentspec pull <id> --registry https://registry.agentspec.dev
```

Agents are stored with their signed profiles — when you pull, you get the agent **with its accumulated experience**.

---

## Base Agent Templates

Pre-built bases in `examples/bases/` for the 4 main runtimes, each with a Noether-flavored variant:

```
bases/
  claude.agent          → claude-noether.agent
  gemini.agent          → gemini-noether.agent
  codex.agent           → codex-noether.agent
  local.agent           → local-noether.agent
```

Extend them in your own agents:

```yaml
base: bases/claude-noether.agent
merge:
  skills: append
behavior:
  traits:
    - my-custom-trait
```

---

## Architecture

```
src/agentspec/
  parser/          Pydantic models, .agent loader, content-addressable hashing
  resolver/        Environment negotiation, inheritance, merge engine
  runner/          Spawns the resolved runtime
  profile/         Persistent identity, memories, portfolio, Ed25519 signing
  registry/        HTTP client for Noether-compatible registries
  cli/             ACLI-compliant CLI (Typer + acli-spec)
```

---

## Testing

```bash
pytest tests/         # 271 tests — parser, merger, resolver, provisioner,
                      # profile, signing (Ed25519 round-trip/tamper/wrong-key),
                      # registry auth, runner, multi-CLI parity
```

---

## License

[EUPL-1.2](https://eupl.eu/) — the European Union Public Licence. Compatible with most other open source licenses (GPL, MIT, Apache via the matrix in the EUPL).

---

## Documentation

Full documentation: [agentspec.dev](https://alpibrusl.github.io/agentspec/)

Or build locally:

```bash
pip install "agentspec-alpibru[docs]"
mkdocs serve
```

---

## Contributing

This is part of a larger ecosystem:

- [agentspec](https://github.com/alpibrusl/agentspec) — this repo
- [noether](https://github.com/alpibrusl/noether) — Noether composition engine
- [noether-cloud](https://github.com/alpibrusl/noether-cloud) — registry + enterprise infra
- [caloron-noether](https://github.com/alpibrusl/caloron-noether) — autonomous sprint orchestrator (uses AgentSpec for agent definitions)
- [acli](https://github.com/alpibrusl/acli) — agent-friendly CLI standard

---

## Project status

**One active maintainer, best-effort response times.** Core (parser + resolver + trust-restricting merger) is stable and tested. Profile signing is stable since 0.4.1. The registry, portfolio profiles, and Noether integration are **alpha** — see [SECURITY.md](./SECURITY.md) before deploying. Not suitable for deployments requiring vendor SLAs.

The package currently ships as `agentspec-alpibru` on PyPI. The `-alpibru` suffix is historical; a rename (with a deprecated alias) is on the roadmap.
