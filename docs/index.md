# AgentSpec

**Trust-restricting inheritance for agent manifests. A resolver turns them into a runnable CLI invocation.**

Write a `.agent` file describing *what* you want. The resolver figures out *how* to run it on your machine — picking a runtime, finding API keys, mapping abstract skills to concrete tools, and telling you what's missing instead of failing mid-execution. Inheritance lets child agents extend parents but **never widen trust** — the merger enforces this invariant at parse time.

```
your .agent file
      ↓
  resolver + trust-restricting merger    ← the defensible bits
      ↓
claude-code / gemini-cli / codex-cli / aider / opencode / ollama
```

## Why AgentSpec exists

Existing agent formats (gitagent, Agent Format, OSSA, Open Agent Spec) are static config files. AgentSpec is two things none of them do:

1. **A trust model.** Agent manifests inherit from other manifests, and a child can only *narrow* the parent's trust — never widen it. Enforced at merge time across three dimensions (filesystem, network, exec).
2. **A resolver.** Given a manifest and the state of your machine (CLIs installed, API keys in env, models available), it picks the concrete runtime + flags that will actually run — or explains what's missing.

Everything else (agent profiles with Ed25519-signed portfolios, gym, Noether composition) is an optional extension on top of this core.

## Three-minute tour

```bash
# Install
pip install agentspec-alpibru

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

**Core:**

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quick Start](getting-started/quickstart.md)** — install and run your first agent in 5 minutes
- :material-file-document: **[The .agent Format](concepts/format.md)** — full specification of the manifest schema
- :material-shield-lock: **[Inheritance & Trust](concepts/inheritance.md)** — the trust-restricting merger
- :material-cog: **[Resolver](concepts/resolver.md)** — how environment negotiation works
- :material-cloud: **[Registry](guides/registry.md)** — push/pull agents (alpha)

</div>

**Extensions:**

<div class="grid cards" markdown>

- :material-account-key: **[Profiles & Signing](concepts/profiles.md)** — persistent signed agent identity (alpha)
- :material-graph: **[Noether Integration](concepts/noether.md)** — composable stages

</div>

## License

[EUPL-1.2](https://eupl.eu/) — European Union Public Licence.
