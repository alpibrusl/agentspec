# The Resolver

The resolver is AgentSpec's unique value. Given a `.agent` manifest, it auto-negotiates everything needed to actually run the agent.

## What it does

```
.agent manifest
      ↓
1. Resolve inheritance chain (base → parent → child)
2. Detect available runtimes (shutil.which("claude"), etc.)
3. Match model preference list to runtime + auth
4. Map abstract skills → concrete tools
5. Resolve MCP tools
6. Build system prompt (from SOUL.md/traits/system_override + RULES.md)
      ↓
ResolvedPlan(runtime, model, tools, auth_source, system_prompt, ...)
```

## Use it

```bash
agentspec resolve researcher.agent
agentspec resolve researcher.agent --output json
```

```python
from agentspec import load_agent, resolve

manifest = load_agent("researcher.agent")
plan = resolve(manifest, verbose=True)

print(plan.runtime)     # claude-code
print(plan.model)       # claude/claude-sonnet-4-6
print(plan.tools)       # [bash, brave-mcp]
print(plan.decisions)   # full trace of every decision
```

## Step 1: Runtime detection

```python
RUNTIME_BINARIES = {
    "claude-code": "claude",
    "gemini-cli": "gemini",
    "cursor": "cursor",
    "codex-cli": "codex",
    "opencode": "opencode",
    "aider": "aider",
    "ollama": "ollama",
}
```

Each binary checked with `shutil.which()`. Plus environment variables: if `OLLAMA_HOST` is set, Ollama is considered available even without the binary (for Docker contexts).

## Step 2: Model matching

The resolver walks `model.preferred` in order. For each model:

1. Parse provider prefix (`claude/`, `gemini/`, `openai/`, `local/`)
2. Look up which runtime serves that provider
3. Check if the runtime is installed
4. Check if the required API key is in env (or `local/` for ollama)
5. First match wins

If no preferred model resolves, the `fallback` capability tier kicks in:

```python
"reasoning-max":  ["claude/claude-opus-4-6", "openai/o3", ...]
"reasoning-high": ["claude/claude-sonnet-4-6", "openai/o3", ...]
"reasoning-mid":  ["claude/claude-haiku-4-5", "openai/gpt-4o", ...]
"reasoning-low":  ["local/llama3:8b", "local/mistral:7b"]
```

## Step 3: Skill resolution

Abstract skills map to concrete tool candidates:

```python
SKILL_MAP = {
    "web-search":     ["brave-mcp", "serper-mcp", "tavily-mcp"],
    "code-execution": ["bash", "python-repl"],
    "browser":        ["playwright-mcp", "puppeteer-mcp"],
    "git":            ["git"],
    "noether-compose": ["noether"],
    # ... extensible
}
```

For each skill, the resolver picks the first candidate available. Skills with no available tool become `missing_tools` (warned, not failed).

## Step 4: System prompt

Built in priority order:

1. `SOUL.md` (directory format) — used verbatim
2. Inline `behavior.persona` + `behavior.traits` — traits expand to prompt fragments
3. `behavior.system_override` — escape hatch
4. `RULES.md` (directory format) — always appended

Trait → prompt mapping:

```python
TRAIT_PROMPTS = {
    "cite-everything":    "Always cite sources with URLs or references.",
    "flag-uncertainty":   "Mark uncertain information with [UNCERTAIN].",
    "never-guess":        "If you don't know something, say so. Never fabricate.",
    "noether-first":      "Prefer Noether compositions over writing code from scratch.",
    # ...
}
```

## Verbose trace

Pass `--verbose` to see every decision:

```
Detected runtimes: [claude-code, gemini-cli, ollama]
  skip claude/claude-sonnet-4-6: ANTHROPIC_API_KEY not set
  selected gemini/gemini-2.5-pro via gemini-cli (env.GOOGLE_API_KEY)
  skill web-search: resolved to brave-mcp
  skill cite-sources: no tool found from [zotero-mcp, arxiv-mcp]
  Cost limit: $0.50
  Step limit: 20
```

This is auditability for free — every choice the resolver made, with the reason.

## Why it matters

Without a resolver:

- Your agent definition hardcodes `model: claude-sonnet-4-6` → breaks if you don't have an Anthropic API key
- You list `tools: [brave-mcp]` → breaks if Brave MCP isn't installed
- You write a system prompt for Claude → breaks on Gemini

With AgentSpec:

- Manifest declares **what** you want (reasoning-high, web-search)
- Resolver figures out **how** based on what's available
- Same manifest runs everywhere, gracefully degrades when tools are missing

## Cold start vs. warm

Cold start (no runtimes installed):

```
$ agentspec resolve researcher.agent
Error: No model could be resolved.
Hint: Install a runtime (claude, gemini, codex, ollama) or set API keys
```

Warm (something available):

```
$ agentspec resolve researcher.agent
  Runtime:  ollama
  Model:    local/llama3:70b
  Auth:     local socket
```

The resolver prefers what you have. You don't need every runtime — one is enough.
