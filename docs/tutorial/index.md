# Tutorial: give `citecheck` an agent

We have a working citation-verification CLI (see the [ACLI tutorial](https://alpibrusl.github.io/acli/tutorial/)) and a composable graph of stages (see the [Noether tutorial](https://alpibrusl.github.io/noether/tutorial/)). Both are tools a human — or an agent — can invoke.

But humans don't want to stitch together a CLI and decide *when* to use `--semantic`, *how* to interpret "partial support", and *whether* to trust a page. That's what an agent is for.

In this tutorial we build a `citation-auditor.agent` — an AgentSpec manifest that:

- Picks the right LLM runtime from your environment (Claude, Gemini, Codex, Aider, opencode, or Ollama)
- Resolves to Vertex AI automatically when you're on GCP
- Calls `citecheck scan` and `citecheck verify --semantic` with sensible defaults
- Accumulates a signed portfolio of past audits (when a bug reviewer asks "has this citation been audited before?" you have the receipt)
- Inherits from a trusted base agent so you can publish variants without re-reviewing trust

Nothing about the `citation-auditor.agent` file is runtime-specific. The same file works on your laptop with Ollama and on Cloud Run with Vertex AI.

| Part | Runs without LLM? | Ends with... |
|---|---|---|
| [1. Quick-start](#quick-start) | ✅ | Validate and resolve an agent — no execution yet |
| [2. Basic example: citation-auditor.agent](#basic-example-citation-auditoragent) | ⚠️ validation without, execution with | Full agent that wraps citecheck |
| [3. Profiles: signed portfolios across audits](#profiles-signed-portfolios-across-audits) | ✅ | A persistent, verifiable record of past work |
| [4. Integrate with code assistants](#integrate-with-code-assistants) | ✅ | Cursor/Claude/Copilot spawn agents via `agentspec run` |
| [5. Where to next](#where-to-next) | — | Caloron tutorial to run autonomous sprints against citecheck |

## Quick-start

```bash
pip install agentspec-alpibru
agentspec version
```

Scaffold an agent — no LLM needed:

```bash
agentspec init my-first --format file
```

This creates `my-first.agent`:

```yaml
apiVersion: agent/v1
name: my-first
version: 0.1.0
description: "my-first agent"

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
# ...
```

Validate it against the schema:

```bash
agentspec validate my-first.agent
```

See what the resolver would pick from your environment — without running anything:

```bash
agentspec resolve my-first.agent
```

Output is a plan: the chosen runtime, model, auth source, skills resolved to concrete tools, and a list of decisions showing why each choice was made. **None of this requires an LLM API call or a network request.** The resolver is pure and offline.

!!! info "The resolver's job"
    Given a `.agent` manifest and your current environment (installed CLIs, API keys, GCP config), the resolver answers: "if I had to run this agent right now, how would I?" It's idempotent, deterministic, and fast — runs in milliseconds.

Now the agent we actually want.

## Basic example: `citation-auditor.agent`

The goal: an agent that, given a Markdown file, runs `citecheck scan`, interprets the output, and produces a report with follow-up recommendations.

### Prerequisite

Install `citecheck` from the [ACLI tutorial](https://alpibrusl.github.io/acli/tutorial/):

```bash
# If you already did the ACLI tutorial:
pip install -e ~/citecheck
citecheck --help    # sanity check

# Or use the reference implementation:
pip install citecheck-tutorial
```

### The manifest

```yaml title="~/citecheck/citation-auditor.agent"
apiVersion: agent/v1
name: citation-auditor
version: 0.1.0
description: Audits citations in Markdown documents using the citecheck CLI.

# Models (with fallback)
model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - openai/o3
    - local/llama3:70b
  fallback: reasoning-mid

# Tools the agent expects to have available
skills:
  - code-execution          # for running the citecheck CLI
  - file-read               # for reading the target Markdown
  - web-search              # to cross-check if citations are disputed

# Behavior — these traits get translated to a system prompt
behavior:
  persona: precise-citation-auditor
  traits:
    - cite-everything
    - flag-uncertainty
    - never-guess
  temperature: 0.2
  max_steps: 15

# Trust — what the agent is allowed to do
trust:
  filesystem: scoped         # can only touch files in scope/
  scope:
    - ./docs
    - ./reports
    - ./audit-runs
  network: allowed           # needs to reach cited URLs via citecheck
  exec: sandboxed            # runs citecheck as a subprocess

# Observability — cost and step ceilings
observability:
  trace: true
  cost_limit: 0.25          # USD per audit
  step_limit: 20
  on_exceed: abort

# Run-it-like-this — the agent's public contract
expose:
  - name: audit
    description: Audit all citations in a Markdown document.
    input:
      file: str
      semantic: "bool | null"
    output: Report
```

Validate it:

```bash
cd ~/citecheck
agentspec validate citation-auditor.agent
```

Output:

```
Valid: citation-auditor@0.1.0 (ag1:f1a2b3c4d5e6)
  skills: code-execution, file-read, web-search
```

That hash — `ag1:f1a2b3c4d5e6` — is the content-addressable identity of this agent. Anyone who can reproduce the same YAML produces the same hash. Two teams publishing "the same" agent get the same ID.

Resolve it against your environment:

```bash
agentspec resolve citation-auditor.agent
```

What you see depends on what you have:

=== "Laptop with Claude API key"
    ```
    Runtime:  claude-code
    Model:    claude/claude-sonnet-4-6
    Auth:     env.ANTHROPIC_API_KEY
    Tools:    bash, read_file, brave-mcp
    ```

=== "Laptop with only Gemini API key"
    ```
    Runtime:  gemini-cli
    Model:    gemini/gemini-2.5-pro
    Auth:     env.GOOGLE_API_KEY
    ```

=== "GCP workstation with Vertex AI"
    ```
    Runtime:  claude-code
    Model:    claude/claude-sonnet-4-6
    Auth:     vertex-ai (project=my-project, region=europe-west1)
    ```

=== "Offline laptop with Ollama"
    ```
    Runtime:  ollama
    Model:    local/llama3:70b
    Auth:     local socket
    ```

The same manifest — four different resolutions. The agent definition stays the same; the runtime adapts to the environment.

### Running it

!!! warning "From here on, you need a runtime"
    The resolver does its job without any LLM call. `agentspec run` actually spawns the chosen runtime — for that you need a reachable LLM.

```bash
agentspec run citation-auditor.agent --input "audit ./docs/report.md"
```

When the agent runs, it:

1. Opens `docs/report.md`
2. Invokes `citecheck scan docs/report.md --output json`
3. Parses the result, decides which links need `--semantic` follow-up
4. Runs `citecheck verify --semantic` for the ambiguous ones
5. Writes a structured report to `reports/audit-<timestamp>.md`
6. Records the audit in the agent's portfolio (next section)

### Inheritance: safer variants

Suppose your organization wants a variant with even stricter trust (no network, only local doc checks):

```yaml title="offline-citation-auditor.agent"
apiVersion: agent/v1
name: offline-citation-auditor
version: 0.1.0
description: Citation auditor with no network access — only verifies what citecheck can check offline.

base: ./citation-auditor.agent     # inherits from the trusted base

merge:
  skills: restrict                 # child can only use a subset of parent skills
  trust: restrict                  # child cannot escalate trust (hardcoded)
  behavior: append

# Only keep what doesn't need network
skills:
  - code-execution
  - file-read

trust:
  filesystem: scoped
  scope:
    - ./docs
    - ./reports
  network: none                    # more restrictive than parent
  exec: sandboxed
```

```bash
agentspec validate offline-citation-auditor.agent
agentspec resolve offline-citation-auditor.agent
```

The merger enforces the trust-restrict invariant at compose time. If a child agent tries to escalate trust beyond its parent, validation fails — **regardless of what the `merge:` block says.**

## Profiles: signed portfolios across audits

An agent without history is a stateless tool. An agent with a signed history is evidence.

AgentSpec profiles persist across runs. Every audit the agent completes is added to its portfolio, with an Ed25519 signature from the supervisor (default: your local key, generated on first use).

The first time you run the agent, its profile is seeded from the manifest — declared skills at 30% confidence, bootstrap memories capturing the persona. After sprints, those skills upgrade to `demonstrated` at higher confidence.

### Inspect a profile

```bash
# Profiles live under the project's configured directory
agentspec profile show citation-auditor
```

Output:

```
Agent: citation-auditor
Hash: ag1:f1a2b3c4d5e6
Profile version: 1.0.0
Supervisor pubkey: 1d1c179ee9639f31...

Skills (3):
  code-execution       demonstrated   confidence=0.70
  file-read            demonstrated   confidence=0.70
  web-search           declared       confidence=0.30

Portfolio (4 sprints):
  sprint-2026-04-10   docs/marketing.md    12/12 citations verified   6m 42s
  sprint-2026-04-11   docs/engineering.md  18/18 citations verified   9m 11s
  ...

Memories (5 validated):
  [caloron:retro.blocker]  Pages with JavaScript-rendered content...
  [caloron:professional.domain_knowledge]  Wikipedia citations often...
  ...
```

Every portfolio entry is individually signed. Anyone with the supervisor's public key can verify a past audit without re-running it.

### Why this matters in regulated contexts

When an auditor (internal or external) asks *"how do you know these citations were verified?"* you can point them at the signed portfolio. Each entry includes:

- The exact input (Markdown file hash)
- The exact output (report hash, verdict distribution)
- The supervisor's signature over both
- Timestamp and runtime metadata

Under the EU AI Act's transparency requirements, or under SOC2 audit, that's the evidence layer. Caloron (next tutorial) uses this same layer to track agents across multiple projects.

## Integrate with code assistants

AgentSpec exposes three things a code assistant can consume:

1. Its own CLI (`agentspec introspect`) — for the assistant to know *how to invoke agents*
2. The `.agent` files in your project — for the assistant to know *what agents are available*
3. The resolver's decisions (`agentspec resolve --output json`) — for the assistant to know *what environment exists right now*

Generate a skill file for the CLI:

```bash
agentspec skill > AGENTSPEC_SKILLS.md
```

### Claude Code

```markdown title="CLAUDE.md"
# Agents in this project

Available agents (check `./*.agent`):
- `citation-auditor.agent` — audit Markdown citations (needs network)
- `offline-citation-auditor.agent` — offline citation auditor

To run an agent:

    agentspec run <agent-file>.agent --input "<task>"

Always run `agentspec resolve <agent>.agent` first to see what runtime
and model will be used. See AGENTSPEC_SKILLS.md for the CLI reference.

Do not modify `.agent` files without explicit permission — they define
trust boundaries and signing policies.
```

### Cursor

```markdown title=".cursor/rules/agents.md"
---
description: Agent definitions & execution rules
globs: ["**/*.agent"]
alwaysApply: false
---

`.agent` files are AgentSpec manifests. Edit them with care:
- `trust:` fields define what the agent is allowed to do — never loosen
- `base:` fields indicate inheritance — trust only restricts, never escalates
- `version:` should follow semver

For agent execution, prefer `agentspec run` over direct LLM API calls.
Portfolios under `./profiles/` are signed and should not be edited by hand.
```

### Copilot

```markdown title=".github/copilot-instructions.md"
## Agents via AgentSpec

This project uses AgentSpec for agent definitions (files ending in `.agent`).

Before suggesting code that calls an LLM directly, check whether an existing
`.agent` covers the use case:

    ls *.agent
    agentspec resolve <file>.agent   # see what would run

Agent trust fields must not be loosened. Child agents inherit restrictions.
```

### Gemini Code Assist / Aider / Codex / opencode

Same pattern. Point the assistant at `AGENTSPEC_SKILLS.md` and the `.agent` files:

```bash
# Aider
aider --read AGENTSPEC_SKILLS.md *.agent

# opencode
mkdir -p .opencode
cp AGENTSPEC_SKILLS.md .opencode/agentspec.md
```

### The agent-loading pattern

A code assistant given access to `agentspec` and your `.agent` files can:

1. `agentspec resolve <file>.agent --output json` to check the plan
2. Decide whether to ask you for confirmation (trust boundaries matter)
3. `agentspec run <file>.agent --input <task>` to execute
4. Read the resulting profile to see whether the agent has done similar work before

This is different from "the assistant writes the agent." The assistant *uses* agents the same way a human does — respecting the trust boundaries and provenance.

## Where to next

- **[ACLI tutorial](https://alpibrusl.github.io/acli/tutorial/)** — the `citecheck` CLI that our agent wraps
- **[Noether tutorial](https://alpibrusl.github.io/noether/tutorial/)** — the composition graph that our agent can call as verified stages
- **[Caloron tutorial](https://alpibrusl.github.io/caloron-noether/tutorial/)** — run an autonomous sprint that extends `citecheck` and creates new variants of `citation-auditor.agent` automatically; the agent's portfolio grows sprint by sprint

Each tutorial builds on this same thread. Read in any order.
