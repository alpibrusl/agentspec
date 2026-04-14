# Registry

Push, pull, and search agents from any Noether-compatible registry.

## Local (no registry)

Default. `push`/`pull` use `./registry/agents/` on local filesystem.

```bash
agentspec push my.agent
agentspec pull ag1:abc123
```

## Public registry

The recommended path for most users is the free, hosted registry at **https://registry.alpibru.com**:

```bash
export AGENTSPEC_REGISTRY=https://registry.alpibru.com

agentspec search "ota pricing"
agentspec pull <stage-id>
agentspec push my.agent          # auth not yet enabled (beta)
```

Beta status: stable, but rate limits and authentication are still being
configured. Run a self-hosted instance for anything sensitive.

## How agents are stored

`.agent` manifests are wrapped as Noether stage specs:

```json
{
  "name": "agent:my-researcher",
  "description": "Cites everything, never guesses",
  "tags": ["agentspec", "agent-manifest", "research"],
  "implementation": "<full manifest as JSON>",
  "input": {"Record": []},
  "output": {"Record": [["manifest", "Any"]]}
}
```

This means:

- The Noether registry treats agents as first-class stages
- Search uses Noether's semantic search (vector embeddings)
- No separate database needed
- Agents and stages share the same infrastructure

## Search

Semantic search via vector embeddings:

```bash
$ agentspec search "ota pricing analyst" --registry https://registry.agentspec.dev
Found 3 agent(s):
  ag1:c3ce  ota-pricing-analyst-v2
    Hotel rate anomaly detection with 15 sprint history
  ag1:7242  ota-rate-monitor
    Real-time rate monitoring across 50 destinations
  ag1:9818  ota-recommendation-engine
    Pricing recommendation based on competitor analysis
```

Results ranked by:

- Semantic similarity to the query
- Signature match (input/output types)
- Example similarity

## Profiles travel with manifests

When you push an agent, its profile (with signed portfolio) travels too:

```bash
agentspec push my-agent.agent --registry ...
# Pushes manifest + profile JSON
# Profile contains: memories, portfolio, skill_proofs, signatures

agentspec pull <hash> --registry ...
# Pulls manifest + profile
# You get the agent WITH its accumulated experience
```

This is the network effect: a well-used agent in production becomes more valuable over time. Pull it and you inherit its sprint history.

## API authentication

Public registry: read free, write requires API key.

```bash
export AGENTSPEC_API_KEY=ak_...
agentspec push my.agent --registry https://registry.agentspec.dev
```

Self-hosted: control via `NOETHER_API_KEY` env var on the registry. If empty, no auth required (dev mode).

## Private registries

Run noether-cloud behind your VPN:

```bash
export AGENTSPEC_REGISTRY=https://registry.internal.mycompany.com
export AGENTSPEC_API_KEY=$(vault read -field=key secret/agentspec/key)

agentspec push internal-tool.agent
```

Your agents stay internal. Browse via the noether-cloud UI.

## Discovery patterns

Find agents by:

- **Domain**: `--tag ota`, `--tag electromobility`, `--tag finance`
- **Capability**: search "pandas pipeline", "code review"
- **Provenance**: filter by signed-by (supervisor pubkey)
- **Recency**: most recently pushed first
- **Reputation**: sort by completion rate, total sprints (in profile)

## Compose with other Noether stages

Once published, your agent is a Noether stage. Compose it with the 370+ existing stages:

```json
{
  "operator": "Sequential",
  "stages": [
    {"stage": "csv_parse"},
    {"stage": "agent:my-researcher"},
    {"stage": "format_report"}
  ]
}
```

```bash
noether run pipeline.json --input data.csv
```

The agent becomes one node in a verified composition graph.
