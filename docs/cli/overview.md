# CLI Overview

`agentspec` is an [ACLI](https://github.com/alpibrusl/acli)-compliant command-line tool. Built with Typer + acli-spec.

## Help

```bash
agentspec --help
agentspec <command> --help
```

## Output formats

All commands support `--output text|json|table`:

```bash
agentspec validate my.agent --output json
```

JSON output uses ACLI's standard envelope:

```json
{
  "ok": true,
  "command": "validate",
  "data": {...},
  "meta": {"duration_ms": 12, "version": "0.1.0"}
}
```

## Discovery

Agents (the LLM kind) can introspect AgentSpec at runtime:

```bash
agentspec introspect          # full command tree as JSON
agentspec skill               # generate SKILLS.md
```

This means an LLM agent given access to the `agentspec` CLI can learn what it can do without you writing custom prompts.

## Commands

| Command | Purpose |
|---|---|
| `init` | Scaffold a new `.agent` project |
| `validate` | Check schema against the spec |
| `resolve` | Show what would run without executing |
| `run` | Resolve and execute |
| `extend` | Scaffold a child agent |
| `push` | Publish to a registry |
| `pull` | Fetch from a registry |
| `search` | Semantic search a registry |
| `schema` | Print the JSON Schema |

See [Commands](commands.md) for full reference.

## Environment variables

| Var | Purpose |
|---|---|
| `AGENTSPEC_REGISTRY` | Default registry URL |
| `NOETHER_REGISTRY` | Fallback registry URL (Noether-compatible) |
| `AGENTSPEC_API_KEY` | API key for write operations |
| `NOETHER_API_KEY` | Fallback API key |
| `ANTHROPIC_API_KEY` | For Claude runtime |
| `GOOGLE_API_KEY` | For Gemini runtime |
| `OPENAI_API_KEY` | For Codex runtime |
| `OLLAMA_HOST` | Ollama URL (when not local) |

## Exit codes

ACLI standard:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Not found |
| 4 | Permission denied |
| 5 | Conflict |
| 6 | Timeout |
| 7 | Upstream error |
| 8 | Precondition failed |
| 9 | Dry run |

Use these in shell scripts:

```bash
if agentspec validate my.agent; then
  agentspec push my.agent --registry $REGISTRY
else
  echo "Invalid manifest, fix before pushing"
  exit 1
fi
```
