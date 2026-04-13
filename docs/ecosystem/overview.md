# The Ecosystem

AgentSpec is one piece of a four-project ecosystem.

## The four projects

### [agentspec](https://github.com/alpibrusl/agentspec) (this repo)

The standard + CLI + SDK + profile system. Open source (EUPL-1.2).

What you write: `.agent` files
What you run: `agentspec run my.agent`

### [noether](https://github.com/alpibrusl/noether)

Verified composition platform. Content-addressed stages, type-safe, composable.

What it provides: stage store, composition engine, `noether serve`/`build`/`compose`
What AgentSpec uses: stages for validate/resolve/merge/hash/evolve/profile operations

### [noether-cloud](https://github.com/alpibrusl/noether-cloud)

The platform: registry server (Rust + Postgres), 370+ stage specs, Docker/K8s/Terraform infra.

What it provides: hosted registry API, semantic search, enterprise features
What AgentSpec uses: agent storage, search, push/pull endpoints

### [caloron-noether](https://github.com/alpibrusl/caloron-noether)

Autonomous sprint orchestrator. PO Agent → DAG → agents → PRs → reviews → retro → evolution.

What it provides: full sprint loop with real Git, real PRs, real code
What AgentSpec uses: agent definitions, profiles for HR Agent context, evolution

## How they fit together

```
┌─────────────────────────────────────────────────────────┐
│  caloron-noether   (sprint orchestration)                │
│    PO Agent → tasks → HR Agent → agents → retro          │
│    uses .agent files + profiles                          │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  agentspec   (manifests + profiles)                      │
│    .agent files + signed profiles                        │
│    resolver + inheritance + portfolio                    │
│    operations registered as Noether stages               │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  noether        (composition engine)                     │
│    typed, content-addressed, composable stages           │
│    serve, build, compose CLI                             │
└────────────────────┬─────────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────────┐
│  noether-cloud   (registry + infra)                      │
│    Rust HTTP server, Postgres, semantic search           │
│    Docker/K8s deployment                                 │
│    Public registry: registry.agentspec.dev               │
└──────────────────────────────────────────────────────────┘
```

## Why one ecosystem

Most agent platforms reinvent every layer. By building on Noether:

| Need | Built once in Noether | Used by AgentSpec |
|---|---|---|
| Content-addressed storage | Stage store with SHA-256 | Agent manifests as stages |
| HTTP serving | `noether serve` | Registry API |
| Compilation | `noether build` | Compile agent compositions |
| Type checking | Engine type-checker | Validate agent compositions |
| Semantic search | Vector embeddings | Find agents by intent |
| Docker/K8s infra | noether-cloud/infra | Same infra serves agents |

Result: AgentSpec ships as Python SDK + CLI. Everything else (registry, infra, distribution) reuses Noether infrastructure.

## Get started

```bash
# Just AgentSpec (CLI + manifests)
pip install agentspec-alpibru

# AgentSpec + local Noether (compositions)
pip install agentspec-alpibru
cargo install --git https://github.com/alpibrusl/noether

# Full stack (with self-hosted registry)
pip install agentspec-alpibru
git clone https://github.com/alpibrusl/noether-cloud
cd noether-cloud/infra && docker compose up

# Sprint orchestration
git clone https://github.com/alpibrusl/caloron-noether
cd caloron-noether && python orchestrator/orchestrator.py "your goal"
```

## License coherence

All projects: [EUPL-1.2](https://eupl.eu/). EU-friendly, open source, compatible with most other open source licenses.
