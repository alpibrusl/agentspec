# Your First Agent

Let's build a research agent that cites everything.

## The manifest

Create `researcher.agent`:

```yaml
apiVersion: agent/v1
name: deep-researcher
version: 1.0.0
description: "Cites everything, never guesses"
tags: [research, web]

model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b
  fallback: reasoning-mid

skills:
  - web-search
  - cite-sources
  - summarize

behavior:
  persona: precise-researcher
  traits:
    - cite-everything
    - flag-uncertainty
    - never-guess
  temperature: 0.2
  max_steps: 15

trust:
  filesystem: none
  network: allowed
  exec: none

observability:
  trace: true
  cost_limit: 0.50
  step_limit: 20
```

## Validate

```bash
$ agentspec validate researcher.agent
Valid: deep-researcher@1.0.0 (ag1:429769c6fa4c)
  skills: web-search, cite-sources, summarize
```

## Resolve

```bash
$ agentspec resolve researcher.agent
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    brave-mcp, arxiv-mcp
```

## Run

```bash
agentspec run researcher.agent --input "What is quantum tunneling?"
```

## What's happening

Three layers of mapping:

1. **Manifest → Runtime**: The resolver checks your environment. You have `claude` installed and `ANTHROPIC_API_KEY` set, so it picks `claude-code` with `claude-sonnet-4-6`.

2. **Skills → Tools**: Abstract skills (`web-search`, `cite-sources`) map to concrete tools available locally (`brave-mcp`, `arxiv-mcp`).

3. **Traits → System Prompt**: The traits `cite-everything`, `flag-uncertainty`, `never-guess` get expanded into a system prompt:

```
You are a precise-researcher.
Always cite sources with URLs or references.
Mark uncertain information with [UNCERTAIN].
If you don't know something, say so. Never fabricate.
```

## Make it portable

The same manifest runs anywhere. If you switch to a machine with only Gemini:

```bash
$ unset ANTHROPIC_API_KEY
$ export GOOGLE_API_KEY=...
$ agentspec resolve researcher.agent
  Runtime:  gemini-cli
  Model:    gemini/gemini-2.5-pro
  Auth:     env.GOOGLE_API_KEY
```

Your agent definition didn't change. The resolver picked the next available option from your `preferred` list.

## Next steps

- [Inheritance](../concepts/inheritance.md) — extend this agent for legal research
- [Profiles](../concepts/profiles.md) — accumulate experience across sprints
- [Base Templates](../guides/bases.md) — start from pre-built agents
