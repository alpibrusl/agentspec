# Quick Start

5 minutes from install to running an agent.

## Install

```bash
pip install agentspec-alpibru
```

For Ed25519 signing (recommended for production):

```bash
pip install "agentspec-alpibru[signing]"
```

## Create your first agent

```bash
agentspec init my-researcher
```

This creates `my-researcher.agent`:

```yaml
apiVersion: agent/v1
name: my-researcher
version: 0.1.0
model:
  capability: reasoning-mid
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b
skills:
  - code-execution
  - file-read
  - file-write
behavior:
  traits:
    - think-step-by-step
    - be-concise
trust:
  filesystem: scoped
  scope: [./workspace]
```

## Validate

```bash
agentspec validate my-researcher.agent
```

```
Valid: my-researcher@0.1.0 (ag1:abc123def456)
  skills: code-execution, file-read, file-write
```

## Resolve

See what would run before actually running:

```bash
agentspec resolve my-researcher.agent
```

```
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    bash
```

## Run

```bash
agentspec run my-researcher.agent --input "What is the capital of France?"
```

The resolver:

1. Detected `claude` in your PATH
2. Found `ANTHROPIC_API_KEY` in your environment
3. Selected the first model whose runtime + auth was available
4. Spawned `claude-code` with the system prompt built from your traits

## What just happened

You wrote a manifest describing **what** you wanted (reasoning-mid model, file access, scoped to `./workspace`). AgentSpec's resolver figured out **how** to make it real (use claude-code with claude-sonnet-4-6 via your API key).

If you only had `gemini` installed and `GOOGLE_API_KEY` set, the same `.agent` file would have run on Gemini instead. That's the resolver — your manifest is portable across environments.

## Next steps

- [Your First Agent](first-agent.md) — write a more interesting agent
- [The .agent Format](../concepts/format.md) — full schema reference
- [Resolver](../concepts/resolver.md) — how environment negotiation works
