# Noether Integration

AgentSpec operations are registered as [Noether](https://github.com/alpibrusl/solv-noether) stages — content-addressed, type-safe, composable units of computation.

## Why Noether?

Noether is a verified composition platform. Every stage is:

- **Content-addressed** — same input bytes → same hash, forever
- **Type-checked** — input/output types validated before execution
- **Composable** — stages chain into graphs, graphs into bigger graphs
- **Trace-recorded** — every execution leaves a trace

By making AgentSpec operations Noether stages, you get:

- All AgentSpec ops are reproducible
- They compose with the 370+ other Noether stages (data, AI, web, infra)
- They can be served as HTTP APIs via `noether serve`
- They can be compiled to standalone binaries via `noether build`

## The 9 AgentSpec stages

```bash
noether stage search "agentspec"
```

| Stage | ID | What |
|---|---|---|
| `agentspec_validate` | `a61021f8` | Schema validation |
| `agentspec_resolve` | `d979bb0b` | Environment negotiation |
| `agentspec_hash` | `dd86f6e2` | Content-addressable hashing |
| `agentspec_merge` | `9df4c9dc` | Inheritance with trust check |
| `agentspec_evolve` | `2a068663` | Retro-based evolution |
| `agentspec_schema` | `7feb167c` | JSON Schema export |
| `agentspec_profile_create` | `7d22e469` | Create profile from manifest |
| `agentspec_profile_retro` | `d8995d46` | Process retro into signed memories |
| `agentspec_profile_export` | `99be6346` | Export profile for registry |

Use them locally:

```bash
echo '{"manifest": {"name": "test", "apiVersion": "agent/v1"}}' | \
  python3 stages/validate.py
```

Or via Noether:

```bash
noether run validate-graph.json --input '{"manifest": ...}'
```

## Composing stages

Build a graph that validates → resolves → creates a profile:

```json
{
  "name": "agent_pipeline",
  "operator": "Sequential",
  "stages": [
    {"stage": "agentspec_validate", "input": "$manifest"},
    {"stage": "agentspec_resolve", "input": "$.previous"},
    {"stage": "agentspec_profile_create", "input": "$.previous"}
  ]
}
```

Run as HTTP:

```bash
noether serve agent_pipeline.json --port 8080
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{"manifest": {"name": "test", ...}}'
```

Or compile to binary:

```bash
noether build agent_pipeline.json --output ./agent-validator
./agent-validator --input <manifest.json>
```

## Noether-flavored bases

`examples/bases/*-noether.agent` — base templates with Noether composition skills baked in:

```yaml
base: ./claude.agent
merge:
  skills: append

skills:
  - noether-compose
  - noether-run
  - noether-search
  - noether-serve

behavior:
  traits:
    - noether-first      # Prefer Noether compositions over writing code
    - noether-verify     # Lint .nth files before running
```

The `noether-first` trait expands to:

> Prefer Noether compositions over writing code from scratch. Use `noether decompose` to break problems into verified stages, `noether search` to find reusable stages in the library, and `noether run` to execute compositions. Noether stages are content-addressed and type-safe — reuse over reinvention.

## In the registry

The [noether-cloud](https://github.com/alpibrusl/noether-cloud) registry stores AgentSpec stages alongside the other 370+:

```bash
NOETHER_REGISTRY=https://registry.agentspec.dev \
  noether stage search "agentspec"
```

When you push a `.agent` manifest, it's wrapped as a Noether stage:

- `name: agent:my-researcher`
- `tags: [agentspec, agent-manifest, ...user_tags]`
- `implementation: <full manifest as JSON>`

`agentspec push` and `agentspec pull` use this convention transparently.

## Why this architecture wins

You don't need a separate AgentSpec registry, server, or infrastructure. You don't need a separate marketplace. Everything runs on the existing Noether infrastructure:

- Registry → Noether stage store (Postgres + semantic search)
- API server → `noether serve`
- Distribution → `noether build` to binaries/WASM
- Composition → mix AgentSpec ops with data/AI/web stages
- Verification → content-addressing + signing

One platform, one set of infrastructure, one ecosystem.
