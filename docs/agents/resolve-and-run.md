# Playbook: resolve-and-run

## Intent

Take an existing `.agent` manifest and execute it: resolve runtime + model + tools, derive an isolation policy from `trust:`, spawn the runtime CLI under bubblewrap, write an execution record.

## Preconditions

- Valid `.agent` manifest (see [`create-an-agent.md`](create-an-agent.md)).
- At least one matching runtime CLI installed for a `model.preferred` entry, with its auth credentials in the environment.
- `bubblewrap` on PATH if the manifest's `trust:` is anything tighter than `filesystem: full, network: allowed, exec: full`.

## Steps

1. **Dry-run the resolver.** Confirms runtime + model + auth pick before spawning anything:

   ```bash
   agentspec resolve my-agent.agent --verbose
   ```

   Verbose mode shows the decision chain (each `preferred:` entry tried in order).

2. **Run.** Default `--via=auto` uses bwrap if installed, falls back on permissive manifests with a warning, refuses on tight manifests without `--unsafe-no-isolation`:

   ```bash
   agentspec run my-agent.agent --input "<input text or JSON>"
   ```

3. **Inspect the execution record.** Every run writes one under `<workdir>/.agentspec/records/<run-id>.json`:

   ```bash
   agentspec records list
   agentspec records show <run-id>
   ```

## Output shape

`agentspec run` (stdout):

```
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    brave-mcp, arxiv-mcp

Launching claude-code...
<runtime output stream>
```

Execution record (`.agentspec/records/<run-id>.json`):

```json
{
  "schema": "agentspec.record/v1",
  "run_id": "01HT…",
  "agent": { "name": "my-agent", "version": "1.0.0", "hash": "ag1:…" },
  "runtime": "claude-code",
  "started_at": "2026-04-21T10:30:45Z",
  "duration_ms": 312,
  "exit_code": 0,
  "outcome": "success",
  "host": { "os": "linux", "arch": "x86_64", "user": "…" }
}
```

Records never contain prompt content, model output, or secrets. They are the audit trail, not the transcript.

## Isolation backends

`--via=<backend>` or `AGENTSPEC_ISOLATION=<backend>`:

| Backend | Behaviour |
|---|---|
| `auto` (default) | Use bwrap if installed; fall back to `none` with warning on permissive manifests; refuse on tight manifests |
| `bwrap` | Direct bwrap argv built by agentspec itself. Fails hard if bwrap missing |
| `none` | No sandbox. Requires `--unsafe-no-isolation` for tight manifests |

`AGENTSPEC_ISOLATION_BACKEND=noether` (separate env var) routes through the `noether-sandbox` binary instead of building the bwrap argv directly. Same primitive, one upstream implementation shared with the noether composition engine. Falls back to direct-bwrap for `filesystem: full` (no noether schema for `--bind / /`).

## Lockfile-pinned runs

For CI or reproducible pipelines, pin first then run:

```bash
agentspec lock my-agent.agent --sign-key-env AGENTSPEC_SIGNING_KEY
agentspec run my-agent.agent \
  --lock my-agent.agent.lock \
  --require-signed \
  --pubkey $AGENTSPEC_PUBKEY
```

`--require-signed` refuses to run unless the lock's Ed25519 signature verifies against `--pubkey`. Manifest hash drift is caught before the subprocess spawns.

## Failure modes

| Exit | Fragment | Cause | Remedy |
|---|---|---|---|
| 1 | `No model could be resolved` | No `preferred` entry matches runtime + auth | `agentspec resolve --verbose`; install a matching CLI or set the required env var |
| 1 | `validation error for AgentManifest` | Manifest doesn't parse | `agentspec validate` for detailed schema errors |
| 2 | `refusing to run without isolation` | Tight trust + no bwrap + no `--unsafe-no-isolation` | Install bwrap, or add `--via=none --unsafe-no-isolation` |
| 2 | `manifest hash … does not match lock's` | Manifest edited since lock | `agentspec lock` to refresh; revert edit if unintentional |
| 2 | `LOCK_NOT_SIGNED` / `LOCK_SIG_INVALID` / `PUBKEY_MALFORMED` | `--require-signed` checks — distinct paths | See `error.code`; don't conflate |
| 3 | `<provider> API error: 401` | Auth env var not what resolver picked | Verify with `--verbose`; rotate or set token |
| 3 | `bwrap: execvp <binary>: No such file or directory` | Sandbox missing system library (ELF loader paths) | Widen trust, or confirm on v0.5.1+ (earlier versions have a known ELF-loader bug) |
| 127 | `failed to spawn command` | Runtime CLI missing from PATH inside sandbox | Check `which <binary>`; manifest may need `filesystem: read-only` with the runtime's deps in scope |

Full contract: see [`debug-a-failed-run.md`](debug-a-failed-run.md).

## Verification

```bash
agentspec resolve my-agent.agent >/dev/null && echo "resolves OK"
agentspec run my-agent.agent --input "ping" --output json | \
  python3 -c "import sys, json; d = json.load(sys.stdin); exit(0 if d.get('ok') else 1)"
```

Second command: agentspec's `--output json` returns `{ok, ...}`; exit 0 means the runtime CLI also exited 0.

## See also

- [`create-an-agent.md`](create-an-agent.md) — authoring before you run.
- [`debug-a-failed-run.md`](debug-a-failed-run.md) — reading failures.
- Human walkthrough: [`docs/tutorial/full-pipeline.md`](../tutorial/full-pipeline.md).
- Trust model: [`docs/concepts/inheritance.md`](../concepts/inheritance.md).
