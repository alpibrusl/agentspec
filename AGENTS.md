# AgentSpec — for AI agents

You are an AI agent reading this to get oriented in the AgentSpec project. This file is the entry point; the playbooks in [`docs/agents/`](docs/agents/) are the operational references.

## What AgentSpec is

A **portable manifest format + runner** for AI agents. You author a `.agent` file declaring model preferences, skills, trust, and observability; AgentSpec's resolver picks a concrete runtime (Claude Code, Gemini CLI, Codex, Ollama, …) and spawns it inside a bubblewrap sandbox derived from the manifest's declared trust. Execution emits an auditable record; plans can be pinned to signed lockfiles.

Primary value: **one manifest, portable across environments**. Laptop → CI → GCP-via-Vertex — no manifest edits.

## Authoritative source

- CLI contract: `agentspec --help` (this is ACLI-shaped — every command returns `{ok, result|error, meta}`).
- Schema: `agentspec schema > schema.json` (emits the full JSON Schema for `.agent` files).
- Source: `src/agentspec/` in this repo.

Docs can drift; the CLI and schema are the truth.

## When to use which playbook

| Your intent | Playbook |
|---|---|
| Create a new `.agent` file from scratch | [`create-an-agent.md`](docs/agents/create-an-agent.md) |
| Validate a manifest; resolve its runtime; run it | [`resolve-and-run.md`](docs/agents/resolve-and-run.md) |
| Read an `agentspec` failure (non-zero exit, stderr line, ACLI envelope) and choose remediation | [`debug-a-failed-run.md`](docs/agents/debug-a-failed-run.md) |

## Playbook shape

Every file in `docs/agents/` follows a fixed skeleton so you know what each section contains:

```
# Playbook: <key>

## Intent
One sentence. What this playbook enables.

## Preconditions
Bullet list. Environment state required.

## Steps
Numbered. Each step includes the exact CLI invocation.

## Output shape
JSON schema fragment. What the command returns.

## Failure modes
Table: error code → cause → remedy.

## Verification
One-liner you can run to sanity-check your reading.

## See also
Cross-references.
```

## Machine-readable resources

| Resource | Command |
|---|---|
| Full CLI tree as JSON | `agentspec --introspect` (ACLI standard — not yet shipped as of v0.5; use `--help` plus the per-command help for now) |
| JSON Schema for `.agent` files | `agentspec schema` |
| Schema for execution records | `cat src/agentspec/records/models.py` (search `record/v1`) |
| Schema for lockfiles | `cat src/agentspec/lock/models.py` (search `lock/v1`) |

## Two boundaries you need to keep straight

Confusing these causes most mis-authored manifests:

| Boundary | Pinned by | Guarantees |
|---|---|---|
| **Reproducibility of the plan** | `agentspec.lock` | Same runtime, model, tools, system-prompt hash resolve on every re-run. Does *not* make LLM output deterministic. |
| **Isolation of the run** | `trust:` block → bubblewrap | Filesystem / network / capabilities the spawned CLI can reach. Enforced at sandbox setup, not at manifest parse. |

The lockfile is an attestation (this plan, signed by this author, at this moment). The sandbox is an enforcement mechanism (this policy, at this run, regardless of what the agent tries).

## Exit code contract

```
0  success
1  parse / IO / resolution failed (no subprocess spawned)
2  validation / policy rejected (post-resolve, pre-spawn)
3  runtime CLI exited non-zero
```

Short rule: 1 = manifest/env, 2 = trust/lock, 3 = the LLM CLI. See [`debug-a-failed-run.md`](docs/agents/debug-a-failed-run.md).

## Related agent-facing resources

- `agentspec records list` / `show` / `verify` — the audit trail for past runs; one JSON per run under `<workdir>/.agentspec/records/`.
- Human-facing documentation under [`docs/tutorial/`](docs/tutorial/) and [`docs/concepts/`](docs/concepts/) if you need narrative context — skip if you're working from the playbooks.
