# The .agent Format

The `.agent` file is the universal manifest. Two equivalent formats supported:

- **Single file** (`researcher.agent`) — simple, hashable, easy to share
- **Directory** (`researcher/`) — `agent.yaml` + optional `SOUL.md` + `RULES.md` for rich identity

## Full schema

```yaml
# ── Metadata ──────────────────────────────────────────────────────
apiVersion: agent/v1                # spec version
name: deep-researcher
version: 1.2.0
author: you@example.com
license: MIT
description: "Research agent that cites everything"
tags: [research, web]

# ── Inheritance ───────────────────────────────────────────────────
base: ./parent.agent                # local path, registry hash, or URL
merge:
  skills: append                    # append | override | restrict
  tools: append
  behavior: override                # override | append (appends traits)
  trust: restrict                   # ALWAYS restrict — hardcoded

# ── Model ─────────────────────────────────────────────────────────
model:
  capability: reasoning-high        # reasoning-low | mid | high | max
  preferred:                        # resolver tries in order
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - openai/o3
    - local/llama3:70b
  fallback: reasoning-mid
  context: full                     # full | 128k | 32k | 8k

# ── Auth ──────────────────────────────────────────────────────────
auth:
  strategy: auto                    # auto | explicit | none
  providers:
    anthropic:
      from: env.ANTHROPIC_API_KEY
    google:
      from: env.GOOGLE_API_KEY

# ── Skills (abstract) ────────────────────────────────────────────
# Resolver maps to concrete tools available in the environment
skills:
  - web-search                      # → brave-mcp | serper-mcp | tavily-mcp
  - code-execution                  # → bash | python-repl
  - file-read
  - file-write
  - cite-sources                    # → zotero-mcp | arxiv-mcp
  - data-analysis                   # → python-repl | jupyter-mcp
  - browser                         # → playwright-mcp | puppeteer-mcp
  - git
  - github
  - noether-compose                 # → noether (when installed)

# ── Tools (concrete) ─────────────────────────────────────────────
tools:
  mcp:
    - github
    - postgres:
        connection: env.DB_URL
        mode: read-only
  native:
    - bash
    - browser

# ── Memory ────────────────────────────────────────────────────────
memory:
  working: session                  # session | none
  long_term: none                   # none | local | external
  shared: false

# ── Behavior ──────────────────────────────────────────────────────
behavior:
  persona: precise-researcher
  traits:                           # portable across models
    - cite-everything
    - flag-uncertainty
    - never-guess
    - ask-before-writing
    - think-step-by-step
    - be-concise
    - self-review
    - test-first
  temperature: 0.2
  max_steps: 20
  on_error: ask                     # ask | retry | fail | skip
  system_override: |                # escape hatch (use sparingly)
    Custom raw system prompt.

# ── Interface (public API surface) ────────────────────────────────
expose:
  - name: research
    description: "Deep research with citations"
    input:
      query: str
    output: Report

# ── Trust ─────────────────────────────────────────────────────────
trust:
  filesystem: read-only             # none | read-only | scoped | full
  network: allowed                  # none | allowed | scoped
  exec: none                        # none | sandboxed | full
  scope:
    - ./workspace                   # paths if filesystem: scoped

# ── Observability ─────────────────────────────────────────────────
observability:
  trace: true
  cost_limit: 0.50                  # USD hard stop
  step_limit: 30
  on_exceed: ask                    # ask | abort

# ── Extensions (runtime-specific) ─────────────────────────────────
extensions:
  x-claude:
    extended_thinking: true
  x-gemini:
    grounding: true
```

## Forward compatibility

Unknown fields are silently ignored (`extra = "ignore"` in Pydantic). Old parsers won't break on new fields. New parsers gracefully accept old manifests.

## Directory format

For richer identity, use a directory:

```
researcher/
  agent.yaml          # manifest (same schema as .agent file)
  SOUL.md             # personality, identity (freeform markdown)
  RULES.md            # hard constraints (injected verbatim)
  skills/             # optional: custom skill modules
  memory/             # optional: persistent context
```

`SOUL.md` example:

```markdown
# Deep Researcher

You are a precise, rigorous research agent.
You treat accuracy as non-negotiable and uncertainty
as information worth surfacing.

## Communication Style
- Formal but accessible
- Always cite sources inline with URLs
- Flag uncertain claims with [UNCERTAIN]
```

`RULES.md` example:

```markdown
## Must Never
- Invent or paraphrase citations
- Claim certainty when uncertain

## Must Always
- Show source URLs for factual claims
```

The resolver auto-detects format and loads `SOUL.md`/`RULES.md` into the system prompt.

## Content addressing

Every manifest gets a content-addressable hash: `ag1:<sha256[:12]>`.

```python
from agentspec import load_agent, agent_hash
manifest = load_agent("researcher.agent")
print(agent_hash(manifest))
# ag1:429769c6fa4c
```

Two manifests with the same content always have the same hash. Used for registry storage and integrity verification.

## Validation

```bash
agentspec validate researcher.agent
agentspec schema --out agent-v1.json   # export JSON Schema
```
