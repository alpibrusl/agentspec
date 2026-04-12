# Multi-Runtime: Same Agent, Different LLMs

The same `.agent` file runs on Claude, Gemini, Codex, Aider, opencode, or local Ollama. The resolver picks based on what's available.

## Example

```yaml
# universal-coder.agent
apiVersion: agent/v1
name: universal-coder
version: 1.0.0

model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - openai/o3
    - local/llama3:70b
  fallback: reasoning-mid

skills:
  - code-execution
  - file-read
  - file-write
```

## Run with Claude

```bash
$ export ANTHROPIC_API_KEY=sk-...
$ agentspec resolve universal-coder.agent
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
```

## Run with Gemini

```bash
$ unset ANTHROPIC_API_KEY
$ export GOOGLE_API_KEY=...
$ agentspec resolve universal-coder.agent
  Runtime:  gemini-cli
  Model:    gemini/gemini-2.5-pro
```

## Run locally

```bash
$ unset ANTHROPIC_API_KEY GOOGLE_API_KEY OPENAI_API_KEY
$ ollama pull llama3:70b
$ agentspec resolve universal-coder.agent
  Runtime:  ollama
  Model:    local/llama3:70b
```

## Fallback chain

If `preferred` exhausts, the resolver uses `fallback` capability:

```yaml
fallback: reasoning-mid
```

Maps to default models for that tier:

```python
"reasoning-mid": [
    "claude/claude-haiku-4-5",
    "openai/gpt-4o",
    "gemini/gemini-2.0-flash",
    "local/llama3:70b",
]
```

## Provider mapping

| Provider prefix | Runtime binary | Env var |
|---|---|---|
| `claude/`, `anthropic/` | `claude` | `ANTHROPIC_API_KEY` |
| `gemini/`, `google/` | `gemini` | `GOOGLE_API_KEY` |
| `openai/` | `codex` | `OPENAI_API_KEY` |
| `local/`, `ollama/` | `ollama` | (none — local socket) |

## Runtime-specific extensions

Runtime-specific config goes in `extensions.x-<provider>` — silently ignored by other runtimes:

```yaml
extensions:
  x-claude:
    extended_thinking: true
  x-gemini:
    grounding: true
  x-openai:
    reasoning_effort: high
```

When the resolver picks Claude, only `x-claude` is used. The others are ignored. No errors.

## What changes between runtimes

| Property | Cross-runtime |
|---|---|
| `behavior.traits` | ✓ portable (expanded to prompts) |
| `behavior.persona` | ✓ portable |
| `behavior.system_override` | ✗ usually model-specific |
| `skills` (abstract) | ✓ portable |
| `tools.mcp` | ✓ if the MCP server is available |
| `trust.*` | ✓ enforced by AgentSpec, not the runtime |
| `extensions.x-*` | ✗ runtime-specific by design |

## Pricing strategy

Use `preferred` as a quality/cost tradeoff:

```yaml
preferred:
  - claude/claude-haiku-4-5    # cheap first
  - claude/claude-sonnet-4-6   # better fallback
  - openai/o3                  # last resort
```

Or environment-aware:

```yaml
preferred:
  - local/llama3:70b           # free if installed
  - claude/claude-haiku-4-5    # cheap API
  - claude/claude-sonnet-4-6   # premium
```

## CI-friendly

In CI, set only the API key you want used:

```yaml
# .github/workflows/agent-test.yml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  # GOOGLE_API_KEY intentionally not set

steps:
  - run: agentspec run my-agent.agent --input "..."
    # Resolver will pick Claude (only available auth)
```
