# AgentSpec

Universal agent manifest standard with resolver.

AgentSpec is the **resolver layer** that sits between agent definitions and runtimes. It auto-negotiates runtime, model, tools, and auth from your environment.

```
your .agent file
      |
  AgentSpec resolver
  (negotiates environment)
      |
claude-code / gemini-cli / codex-cli / ollama / cursor / aider
```

## Install

```bash
pip install agentspec
```

## Quick Start

```bash
# Create a new agent
agentspec init my-researcher

# Validate it
agentspec validate my-researcher.agent

# See what would run (without executing)
agentspec resolve my-researcher.agent

# Run it
agentspec run my-researcher.agent --input "quantum tunneling"
```

## The `.agent` Format

```yaml
apiVersion: agent/v1
name: deep-researcher
version: 1.0.0

model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b

skills:
  - web-search
  - cite-sources

behavior:
  traits:
    - cite-everything
    - never-guess
  temperature: 0.2

trust:
  filesystem: none
  network: allowed
  exec: none
```

## Two Formats

**Single file** (`researcher.agent`) — simple, shareable, hashable.

**Directory** (`researcher/`) — rich identity with SOUL.md + RULES.md:

```
researcher/
  agent.yaml     # manifest
  SOUL.md        # identity, personality (freeform markdown)
  RULES.md       # hard constraints (injected verbatim)
```

## Inheritance

Agents can extend other agents with enforced merge semantics:

```yaml
base: ./researcher.agent
merge:
  skills: append      # append | override | restrict
  tools: append
  behavior: override
  trust: restrict     # always restrict — child cannot escalate
```

The `trust: restrict` invariant is hardcoded. A child agent can **never** escalate permissions beyond its parent.

## The Resolver

The unique value. Given a `.agent` file, the resolver:

1. Detects installed runtimes (claude, gemini, codex, ollama)
2. Checks API keys in environment
3. Matches the preference list to what's available
4. Maps abstract skills to concrete tools
5. Builds the system prompt from traits/SOUL.md/RULES.md
6. Explains every decision with `--verbose`

```bash
agentspec resolve researcher.agent
#   Runtime:  claude-code
#   Model:    claude/claude-sonnet-4-6
#   Auth:     env.ANTHROPIC_API_KEY
#   Tools:    brave-mcp
```

## ACLI Compliant

Built with [ACLI](https://github.com/alpibrusl/acli) — agents can discover capabilities:

```bash
agentspec introspect          # full command tree as JSON
agentspec skill               # generate SKILLS.md
agentspec --help              # structured help
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `run` | Resolve and execute an agent |
| `validate` | Validate a .agent file against the schema |
| `resolve` | Show what would run without executing |
| `extend` | Scaffold a child agent from an existing one |
| `push` | Publish an agent to the local registry |
| `pull` | Fetch an agent from the registry |
| `schema` | Print the JSON Schema for .agent files |
| `init` | Scaffold a new .agent project |

## License

EUPL-1.2
