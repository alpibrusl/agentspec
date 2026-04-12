# Installation

## Requirements

- Python 3.11+
- One or more LLM runtimes installed:
  - `claude` (Claude Code CLI)
  - `gemini` (Gemini CLI)
  - `codex` (Codex CLI)
  - `aider`
  - `opencode`
  - `ollama` (for local models)

## Install

```bash
pip install agentspec-alpibru
```

## Optional extras

| Extra | Adds | When you need it |
|---|---|---|
| `[signing]` | PyNaCl (Ed25519) | Real cryptographic signatures for profiles |
| `[registry]` | FastAPI + uvicorn | Run a self-hosted registry server |
| `[docs]` | MkDocs + Material theme | Build documentation locally |
| `[dev]` | pytest, ruff, mypy | Contribute to AgentSpec |

```bash
pip install "agentspec-alpibru[signing,registry]"
```

## Verify

```bash
agentspec --help
agentspec version
```

## Set up at least one runtime

AgentSpec doesn't ship with LLM runtimes — it spawns whatever you have installed. Get at least one:

=== "Claude Code"

    ```bash
    npm install -g @anthropic-ai/claude-code
    export ANTHROPIC_API_KEY=sk-...
    ```

=== "Gemini CLI"

    ```bash
    npm install -g @google/gemini-cli
    export GOOGLE_API_KEY=...
    ```

=== "Ollama (local)"

    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull llama3:8b
    ```

=== "Aider"

    ```bash
    pip install aider-chat
    export ANTHROPIC_API_KEY=sk-...   # or OPENAI_API_KEY
    ```

## What's next

- [Quick Start](quickstart.md) — write and run your first agent
- [Multi-runtime](../guides/multi-runtime.md) — same agent on multiple runtimes
