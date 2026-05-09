# Playbook: debug-a-failed-run

## Intent

Take a non-zero `agentspec` exit, classify it by exit code + error fragment, choose the remediation.

## Preconditions

- Access to the user's command (exact argv), stderr line, ACLI envelope on stdout, and — for exit 3 — the execution record under `<workdir>/.agentspec/records/`.
- The manifest and (if applicable) lockfile the run used.

## Steps

1. **Classify by exit code first.** This narrows the failure class before you read any message text.

   | Exit | Class | Happened at |
   |---|---|---|
   | `0` | Success | — |
   | `1` | Parse / IO / resolution | Before the runner spawned anything |
   | `2` | Validation / policy | Post-resolve, pre-spawn |
   | `3` | Runtime | Inside the spawned CLI |
   | `127` | Binary not found at exec time | Inside sandbox; runtime CLI missing from PATH |

2. **Parse the ACLI envelope.** agentspec failures are structured:

   ```json
   { "ok": false, "command": "<cmd>", "error": { "code": "<CODE>", "message": "…", "hint": "…" }, "meta": {…} }
   ```

   Match on `error.code`, not on `error.message` (messages can change; codes are the contract).

3. **Apply the table below.**

## Failure modes

### Exit 1 — pre-resolution

| `error.code` / fragment | Cause | Remedy |
|---|---|---|
| `FILE_NOT_FOUND` / `failed to read <path>` | Missing manifest | Check the path; confirm working dir |
| `INVALID_MANIFEST` / `validation error for AgentManifest` | Schema violation | Run `agentspec validate` — it prints the field-level errors |
| `NO_MODEL_RESOLVED` / `No model could be resolved` | No `preferred` entry matches runtime + auth | `agentspec resolve --verbose` shows the chain; install a CLI or set the required env key |
| `AMBIGUOUS_AGENT_PATH` / `Unknown agent format` | File doesn't end in `.agent` and isn't a dir | Rename, or point at the directory containing a `manifest.agent` |

### Exit 2 — policy rejection

| `error.code` / fragment | Cause | Remedy |
|---|---|---|
| `ISOLATION_UNAVAILABLE` / `refusing to run without isolation` | Tight trust + bwrap missing, no `--unsafe-no-isolation` | Install bwrap; or `--via=none --unsafe-no-isolation` if the trust really is permissive |
| `MANIFEST_LOCK_MISMATCH` / `manifest hash … does not match lock's` | Manifest edited after lock written | Re-lock if intentional; revert edit otherwise |
| `LOCK_NOT_SIGNED` | `--require-signed` passed but lock has no signature envelope | Re-lock with `--sign-key-env <VAR>` |
| `LOCK_SIG_INVALID` | Signature verifies as malformed or doesn't match pubkey | Wrong pubkey **or** lock was tampered. Do not proceed without investigating |
| `PUBKEY_MALFORMED` | The `--pubkey <hex>` arg isn't 32 bytes of valid hex | Distinct from signature check; fix the key argument |
| `COST_BUDGET_EXCEEDED` (pre-flight estimate) | `observability.cost_limit` lower than estimated usage | Raise the limit or narrow the plan |

### Exit 3 — runtime failure

The runtime CLI itself exited non-zero. Read the line following `Launching <runtime>...` for the provider's own error.

| Fragment | Cause | Remedy |
|---|---|---|
| `401 Unauthorized` / `403 Forbidden` | Auth token expired or wrong | Check which env var the resolver picked (`Auth: env.<NAME>` in the run banner); rotate |
| `rate_limit` / `429` | Provider throttling | Back off, reduce concurrency, or swap to next `preferred` entry |
| `timeout` with sandbox `network: none` | Stage declared no network; provider call blocked | Widen `trust.network` to `allowed` or confirm offline mode is intended |
| `bwrap: execvp <binary>: No such file or directory` | On host, binary exists; inside sandbox, ELF interpreter unreachable | v0.5.1+ fixes the `/lib64` symlink case. Earlier: update, or widen `trust.filesystem` |
| Runtime-specific stack trace | Bug in the runtime CLI | Reproduce outside agentspec (`claude-code -p "…"`) to confirm |

### Exit 127 — exec not found inside sandbox

| Fragment | Cause | Remedy |
|---|---|---|
| `failed to spawn command` | Runtime CLI missing from PATH inside bwrap's view | Confirm CLI is under a bound system path (`/usr/bin`, `/nix/store`). Under very tight trust, include it in `trust.scope:` |

## Diagnostic signals from the record

Even a failed run produces an execution record. Two fields are load-bearing:

```json
{ "exit_code": 3, "outcome": "runtime_error", "duration_ms": 42 }
```

| `duration_ms` range | Likely story |
|---|---|
| `< 100` | Sandbox or CLI startup failed before the provider call; check stderr |
| `100 – 2000` | Auth validation or early rejection |
| `> 2000` | Reached the provider; read the runtime's own error |

## When the record says success but output is wrong

Records track exit code + duration, not LLM output quality. Enable `observability.trace: true` in the manifest and pair with the runtime's own logging (e.g. `claude-code --verbose`, Gemini CLI traces). AgentSpec's job is "did the process run under the declared policy;" it does not judge the LLM's reasoning.

## Verification

```bash
# Did the run finish? Exit code is the fastest signal.
echo $?

# Structured envelope if JSON output was requested.
agentspec run … --output json | python3 -c "import sys,json; e=json.load(sys.stdin); print(e.get('ok'), e.get('error', {}).get('code'))"

# Record for any run, regardless of exit:
agentspec records show <run-id>
```

## See also

- [`create-an-agent.md`](create-an-agent.md) — for exit-1 manifest-shape errors.
- [`resolve-and-run.md`](resolve-and-run.md) — the happy path the failure diverged from.
- Human version: [`docs/tutorial/when-things-go-wrong.md`](../tutorial/when-things-go-wrong.md).
