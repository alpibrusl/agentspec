# API: Resolver

```python
from agentspec import resolve, ResolvedPlan, load_agent
from agentspec.resolver.merger import resolve_inheritance, TrustEscalationError

manifest = load_agent("my.agent")
plan = resolve(manifest, verbose=True)
```

## `resolve(manifest, verbose=False) -> ResolvedPlan`

Auto-negotiates runtime, model, tools, auth, and system prompt.

Steps:

1. Resolves inheritance chain (recursive)
2. Detects available runtimes (`shutil.which`)
3. Matches model preferences to runtime + auth
4. Maps abstract skills to concrete tools
5. Resolves MCP tools
6. Builds system prompt

Raises `RuntimeError` if no model can be resolved.

## `ResolvedPlan`

```python
@dataclass
class ResolvedPlan:
    runtime: str             # e.g. "claude-code"
    model: str               # e.g. "claude/claude-sonnet-4-6"
    tools: list[str]
    missing_tools: list[str]
    auth_source: str         # e.g. "env.ANTHROPIC_API_KEY"
    system_prompt: str
    warnings: list[str]
    decisions: list[str]     # full trace

    def to_dict(self) -> dict:
        ...
```

## `resolve_inheritance(manifest) -> AgentManifest`

Walks the `base:` chain, merging according to `merge:` strategy. Enforces trust-restrict invariant.

Raises `TrustEscalationError` if child tries to escalate trust.

```python
from agentspec.resolver.merger import resolve_inheritance, TrustEscalationError

try:
    merged = resolve_inheritance(child_manifest)
except TrustEscalationError as e:
    print(f"Refused: {e}")
```

## `RUNTIME_BINARIES`

```python
{
    "claude-code": "claude",
    "gemini-cli": "gemini",
    "cursor": "cursor",
    "codex-cli": "codex",
    "opencode": "opencode",
    "aider": "aider",
    "ollama": "ollama",
}
```

Override by patching for testing:

```python
from unittest.mock import patch

@patch("agentspec.resolver.resolver._detect_runtimes")
def test_my_thing(mock_runtimes):
    mock_runtimes.return_value = {"claude-code": True, ...}
```

## `SKILL_MAP`

```python
{
    "web-search":     ["brave-mcp", "serper-mcp", "tavily-mcp"],
    "code-execution": ["bash", "python-repl"],
    "browser":        ["playwright-mcp", "puppeteer-mcp"],
    "git":            ["git"],
    "github":         ["github-mcp"],
    "noether-compose": ["noether"],
    # ... extensible
}
```

Add custom mappings:

```python
from agentspec.resolver.resolver import SKILL_MAP
SKILL_MAP["my-custom-skill"] = ["my-tool"]
```

## `TRAIT_PROMPTS`

Maps known traits to prompt fragments:

```python
{
    "cite-everything":    "Always cite sources with URLs or references.",
    "flag-uncertainty":   "Mark uncertain information with [UNCERTAIN].",
    "never-guess":        "If you don't know something, say so. Never fabricate.",
    "noether-first":      "Prefer Noether compositions over writing code...",
    # ...
}
```

Unknown traits pass through verbatim — they're added to the system prompt as-is.
