# Base Agent Templates

Pre-built `.agent` files in `examples/bases/` that you extend instead of writing from scratch.

## Available bases

```
examples/bases/
  claude.agent           ← Claude Code (general-purpose)
  claude-noether.agent   ← Claude + Noether composition skills
  gemini.agent           ← Gemini CLI (general-purpose)
  gemini-noether.agent   ← Gemini + Noether
  codex.agent            ← Codex CLI (OpenAI)
  codex-noether.agent    ← Codex + Noether
  local.agent            ← Local Ollama (no API keys)
  local-noether.agent    ← Local + Noether
```

## Extend a base

```yaml
# my-pricing-analyst.agent
apiVersion: agent/v1
name: ota-pricing-analyst
version: 1.0.0
description: "Analyzes hotel rate data, detects anomalies"

base: ./bases/claude-noether.agent

merge:
  skills: append
  tools: append
  behavior: append
  trust: restrict

# Add domain-specific skills on top
skills:
  - data-analysis

tools:
  mcp:
    - postgres
        connection: env.OTA_DB_URL
        mode: read-only

behavior:
  traits:
    - cite-everything    # for data sources
  temperature: 0.1       # stricter than parent's 0.2

# Tighter sandbox than parent
trust:
  scope: [./src, ./tests, ./reports]
```

## Why bases matter

- **Consistency** — every agent in a team uses the same baseline behavior, trust, and runtime preferences
- **Less duplication** — define common config once
- **Auditability** — security teams approve the base, individual agents can only restrict further
- **Evolution** — improving a base improves all child agents

## What each base provides

### `claude.agent` / `gemini.agent` / `codex.agent`

- `reasoning-high` capability tier
- `senior-developer` persona
- Traits: `think-step-by-step`, `be-concise`, `self-review`
- Trust: `filesystem: scoped` to `./src`, `./tests`, `./docs`
- `network: allowed`, `exec: sandboxed`
- Tools: `bash`, `browser`, `mcp:github`

### `local.agent`

- `reasoning-mid` (smaller models)
- No network access (`network: none`)
- No GitHub MCP (no API keys)
- Same trust scopes

### `*-noether.agent` (all four)

Inherit from their plain base + add:

- Skills: `noether-compose`, `noether-run`, `noether-search`, `noether-serve`
- Traits: `noether-first`, `noether-verify`
- Trust scope: + `./compositions`, `./stages`

## Cookbook

### A pricing analyst

```yaml
base: ./bases/claude-noether.agent
skills:
  - data-analysis
tools:
  mcp:
    - postgres:
        connection: env.PRICING_DB_URL
behavior:
  persona: pricing-analyst
  temperature: 0.0    # deterministic
```

### A frontend developer

```yaml
base: ./bases/codex.agent
skills:
  - code-execution
tools:
  native:
    - npm
    - playwright
behavior:
  persona: frontend-engineer
  traits:
    - test-first
trust:
  scope: [./src, ./tests, ./public]
```

### A local-only research assistant

```yaml
base: ./bases/local.agent
model:
  preferred:
    - local/llama3:70b
behavior:
  persona: researcher
  traits:
    - cite-everything
    - never-guess
```

## Publishing your own bases

Push your bases to the registry so your team can extend them:

```bash
agentspec push my-org-base.agent --registry https://registry.mycompany.com
```

Then in any agent:

```yaml
base: ag1:abc123def456    # registry hash
```

Or by name:

```yaml
base: my-org/standard-base@1.0.0
```
