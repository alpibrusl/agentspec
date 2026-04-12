# AgentSpec

**Universal agent manifest standard with resolver, signed profiles, and Noether composition.**

AgentSpec is the missing layer between agent definitions and runtimes. Write a `.agent` file describing *what* you want — the resolver figures out *how* to run it, accumulates *what* the agent learns, and produces a verifiable portfolio of completed work.

```
your .agent file
      ↓
  AgentSpec resolver        ← auto-negotiates environment
  (model, tools, runtime, auth, system prompt)
      ↓
claude-code / gemini-cli / codex-cli / aider / opencode / ollama
      ↓
  Sprint completes → signed profile entry
```

## Why AgentSpec exists

Every existing agent format (gitagent, Agent Format, OSSA) is a static config file. None of them resolve. None of them accumulate experience. None of them produce verifiable agent CVs.

AgentSpec fills three gaps:

1. **The resolver layer** — auto-negotiates runtime, model, tools, and auth from the local environment
2. **Signed profiles** — agents accumulate cryptographically signed portfolios across sprints
3. **Noether integration** — operations are content-addressed, type-safe, composable stages

## Three-minute tour

```bash
# Install
pip install agentspec

# Create
agentspec init my-researcher

# Resolve (see what would run)
agentspec resolve my-researcher.agent

# Run
agentspec run my-researcher.agent --input "quantum tunneling"

# Push to registry
agentspec push my-researcher.agent --registry https://registry.agentspec.dev

# Find agents with proven track records
agentspec search "ota pricing" --registry https://registry.agentspec.dev
```

## Where to next

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quick Start](getting-started/quickstart.md)** — install and run your first agent in 5 minutes
- :material-file-document: **[The .agent Format](concepts/format.md)** — full specification of the manifest schema
- :material-cog: **[Resolver](concepts/resolver.md)** — how environment negotiation works
- :material-account-key: **[Profiles & Signing](concepts/profiles.md)** — verifiable agent CVs
- :material-graph: **[Noether Integration](concepts/noether.md)** — composable stages
- :material-cloud: **[Registry](guides/registry.md)** — push/pull agents

</div>

## License

[EUPL-1.2](https://eupl.eu/) — European Union Public Licence.
