# Commands

## `init`

Scaffold a new `.agent` project.

```bash
agentspec init my-agent
agentspec init my-agent --format directory   # creates my-agent/ folder
```

## `validate`

Validate a `.agent` file or directory against the schema.

```bash
agentspec validate my.agent
agentspec validate ./my-agent/             # directory format
agentspec validate my.agent --output json
```

## `resolve`

Show what would run without executing. Always verbose.

```bash
agentspec resolve my.agent
agentspec resolve my.agent --output json
```

Output:

```
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    bash, brave-mcp
```

## `run`

Resolve and execute.

```bash
agentspec run my.agent --input "your prompt"
agentspec run my.agent --input "..." --dry-run   # resolve but don't execute
agentspec run my.agent --input "..." --verbose
```

`--dry-run` prints the resolved plan and exits with code 9.

## `extend`

Scaffold a child agent that extends an existing one.

```bash
agentspec extend bases/claude.agent --out my-coder.agent
```

Produces a starter `.agent` file with `base:` set and `merge:` defaults.

## `push`

Publish an agent to a registry.

```bash
# Local registry (default)
agentspec push my.agent

# Remote Noether registry
agentspec push my.agent --registry http://localhost:3000
agentspec push my.agent --registry https://registry.agentspec.dev
```

If the agent has a profile (`./profiles/<name>.profile.json`), the profile is pushed too.

## `pull`

Fetch an agent from a registry.

```bash
# By content hash
agentspec pull ag1:abc123def456

# From remote registry
agentspec pull <noether-stage-id> --registry http://localhost:3000

# By search query (returns first match)
agentspec pull "ota pricing analyst" --registry https://registry.agentspec.dev
```

## `search`

Semantic search a remote registry.

```bash
agentspec search "researcher with citations" --registry https://registry.agentspec.dev
agentspec search "ota pricing" --registry https://registry.agentspec.dev --output json
```

Results ranked by semantic similarity.

## `schema`

Print the JSON Schema for `.agent` files.

```bash
agentspec schema
agentspec schema --out agent-v1.json
```

Use the schema to validate manifests in other tools (VSCode YAML, JSON Schema validators).

## Built-in (ACLI-injected)

These commands are automatically provided by the [acli-spec](https://github.com/alpibrusl/acli) SDK:

### `introspect`

Full command tree as JSON, for agent consumption:

```bash
agentspec introspect --output json
```

### `version`

```bash
agentspec version
agentspec version --output json
```

### `skill`

Generate a `SKILLS.md` file describing the CLI for an agent:

```bash
agentspec skill > SKILLS.md
```
