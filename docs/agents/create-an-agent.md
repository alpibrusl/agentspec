# Playbook: create-an-agent

## Intent

Author a new `.agent` manifest that the resolver can pick a concrete runtime for and the runner can execute under a trust-derived sandbox.

## Preconditions

- `agentspec` on PATH (`pip install agentspec-alpibru`).
- Optional: `bubblewrap` installed if you intend to exercise non-permissive trust.
- Optional: one of the shared runtime CLIs (`claude-code`, `gemini-cli`, `cursor-cli`, `opencode`, `codex-cli`, `goose`, `aider`, `ollama`) on PATH, with matching API keys — only required to **run** the agent, not to author it.

## Steps

1. Scaffold the manifest:

   ```bash
   agentspec init my-agent --format file
   ```

   Writes `my-agent.agent` with sane defaults.

2. Edit for intent. Minimum viable shape:

   ```yaml
   apiVersion: agent/v1
   name: my-agent
   version: 0.1.0
   description: "One-line intent"

   model:
     capability: reasoning-mid
     preferred:
       - claude/claude-sonnet-4-6
       - gemini/gemini-2.5-pro
       - local/llama3:70b

   skills: [web-search, summarize]

   behavior:
     persona: research-assistant
     traits: [cite-everything, never-guess]

   trust:
     filesystem: none
     network: allowed
     exec: none

   observability:
     trace: true
     cost_limit: 0.50
   ```

3. Validate against the schema:

   ```bash
   agentspec validate my-agent.agent
   ```

4. Resolve without running to confirm the environment picks a runtime:

   ```bash
   agentspec resolve my-agent.agent --verbose
   ```

## Output shape

`agentspec validate my-agent.agent` on success prints:

```
Valid: <name>@<version> (ag1:<12-char-prefix>)
  skills: skill1, skill2, …
```

The `ag1:<hex>` prefix is the manifest's content hash. Lockfiles pin to it.

## Required fields

| Field | Type | Must |
|---|---|---|
| `apiVersion` | literal `agent/v1` | Exact match; schema rejects other values |
| `name` | string, lowercase kebab | Stable identifier across versions |
| `version` | semver string | Increment on behaviour change |
| `model.preferred` | `[provider/model]` list | At least one entry; tried in order |
| `trust.filesystem` | `none \| read-only \| scoped \| full` | Required — resolver has no default |
| `trust.network` | `none \| scoped \| allowed` | Required |
| `trust.exec` | `none \| full` | Required |

Optional but load-bearing:

| Field | Why |
|---|---|
| `skills` | Abstract → concrete tool mapping via the resolver's skill-to-MCP table |
| `behavior.persona` / `traits` / `rules` / `soul` | Builds the system prompt (`soul` takes priority) |
| `observability.cost_limit` | Budget cap in USD the runtime can consume before halt |
| `observability.step_limit` | Max tool-use iterations |
| `tags` | Free-form discovery hints for the registry |

## Failure modes

| Error fragment | Cause | Remedy |
|---|---|---|
| `1 validation error for AgentManifest: apiVersion` | Wrong / missing `apiVersion` | Set to exactly `agent/v1` |
| `model: Input should be a valid dictionary or instance of ModelSpec` | Passed `model: "provider/name"` as a bare string | Use the dict shape with `preferred: [...]` |
| `trust: Field required` | Omitted the `trust` block | Add it — no sensible default exists |
| `Unknown agent format` | File extension isn't `.agent` | Rename |

## Verification

```bash
agentspec validate my-agent.agent && \
  agentspec resolve my-agent.agent >/dev/null && \
  echo "manifest author & resolve OK"
```

If both commands exit 0, the manifest is schema-valid AND the current environment can pick a runtime for it.

## See also

- [`resolve-and-run.md`](resolve-and-run.md) — what happens after you hand the manifest to `agentspec run`.
- [`debug-a-failed-run.md`](debug-a-failed-run.md) — if validate or resolve errors.
- Schema: `agentspec schema` (authoritative, always in sync with the running binary).
- Base templates in `examples/bases/` — inherit from them with `extends:` rather than re-authoring common shapes.
