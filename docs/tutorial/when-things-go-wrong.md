# When things go wrong: reading AgentSpec failures

Every `agentspec` command exits with one of four codes; every failure prints a structured envelope on stdout with a short error line on stderr. This page is the human-paced version of what to do when you see a non-zero exit.

| Exit | Class | When |
|---|---|---|
| `0` | Success | — |
| `1` | Parse / IO / resolution | Before the runner spawned anything |
| `2` | Validation / policy | After resolution, before execution |
| `3` | Runtime | During the spawned CLI's execution |

Short rule: **1 = your manifest or env, 2 = your trust/lock policy, 3 = the LLM CLI itself**.

---

## Exit 1 — the manifest or resolver failed

Nothing spawned. The error message tells you which stage broke.

```bash
$ agentspec run my.agent
{ "ok": false, "error": { "code": "…", "message": "No model could be resolved." } }
```

| Message fragment | Cause | Remedy |
|---|---|---|
| `failed to read <path>` | File missing or unreadable | Check path; `ls` the parent directory |
| `validation error for AgentManifest` | YAML doesn't conform to the `agent/v1` schema | Run `agentspec validate my.agent` — the errors are more detailed there |
| `No model could be resolved` | None of `model.preferred` matched an installed CLI + auth pair | `agentspec resolve --verbose` shows what the resolver tried |
| `Unknown agent format` | File doesn't end in `.agent` and isn't a directory | Rename, or pass the directory containing the manifest |

### Diagnosing `No model could be resolved`

```bash
$ agentspec resolve my.agent --verbose
  Decisions:
    - Detected runtimes: [claude-code, ollama]
    - claude/claude-sonnet-4-6: runtime OK, auth MISSING (ANTHROPIC_API_KEY)
    - gemini/gemini-2.5-pro: runtime MISSING (gemini)
    - local/llama3:70b: runtime OK, no auth needed, selected
```

Each `preferred:` entry is tried in order. Auth-present + runtime-installed wins. If all three miss, you get exit 1.

The resolver is a **strictly local** query — no network calls, no subprocess spawns beyond `shutil.which` (and `llm-here detect` when installed). It shouldn't hang. If it does, file a bug.

---

## Exit 2 — policy rejected the run

Resolution succeeded, but a pre-flight check refused to let the subprocess start.

### Trust violations

```
refusing to run without isolation: bubblewrap not found on PATH
```

Your manifest declares non-trivial `trust:` (anything other than `filesystem: full, network: allowed, exec: full`), but bwrap isn't installed and you didn't pass `--unsafe-no-isolation`. Either install bwrap or acknowledge the widening explicitly:

```bash
$ agentspec run my.agent --via=none --unsafe-no-isolation
```

The `--unsafe-no-isolation` flag is intentionally awkward to type — it's an informed-consent gate, not a convenience.

### Lock mismatch

```
manifest hash ag1:aaaa… does not match lock's recorded hash ag1:bbbb…
```

Someone (maybe you, 30 seconds ago) edited the manifest since the lockfile was generated. Re-lock if the drift is intentional:

```bash
$ agentspec lock my.agent
```

…or revert the manifest edit if it wasn't.

### `--require-signed` failed

```
INVALID: lock is not a signed envelope, or signature does not verify
```

Three distinct cases, distinguished by the error variant in the JSON envelope:

| `error.code` | Cause | Remedy |
|---|---|---|
| `LOCK_NOT_SIGNED` | The lockfile has no signature envelope | Re-lock with `--sign-key-env VAR` |
| `LOCK_SIG_INVALID` | Signature verifies as *malformed* or wrong for the pubkey | You have the wrong pubkey, or the lock was tampered with — do not proceed |
| `PUBKEY_MALFORMED` | Your `--pubkey <hex>` isn't 32 bytes of valid hex | Fix the key argument; distinct from the signature check |

The third bucket is a distinct error path because "I typo'd the key" and "someone tampered the lock" are operationally different. Don't conflate them in your CI error handling.

---

## Exit 3 — the spawned CLI failed

The runtime (Claude, Gemini, Codex, etc.) started and exited non-zero.

```
Launching claude-code...
claude-code: API error: 401 Unauthorized
```

| Symptom | Cause | Remedy |
|---|---|---|
| `401`/`403` on a provider API | Auth isn't what the resolver thought it was | Check the env var the resolver identified (`Auth: env.ANTHROPIC_API_KEY`) actually has a valid token |
| `execvp <binary>: No such file or directory` | Under isolation, the runtime CLI can't find a system library inside the sandbox | Your `trust: filesystem` is tighter than the runtime's needs allow — either widen or add to `scope:` |
| `timeout` / stalled | Provider slow, token-rate limit, or sandbox blocked network | `trust: network: none` disables network — inspect the manifest |
| runtime-specific stack trace | Bug in the runtime itself | Not ours; reproduce outside AgentSpec to confirm |

### Reading isolation-specific failures

Under `--via=bwrap` (default), `bwrap: execvp <binary>: No such file or directory` on a binary that exists on the host usually means the ELF loader can't resolve its interpreter inside the sandbox — typically `/lib64/ld-linux-x86-64.so.2` on glibc distros. Fixed in v0.5.1+ by binding symlinked system paths; if you're seeing this on v0.5.1+, file a bug with your distro and the manifest.

Under `AGENTSPEC_ISOLATION_BACKEND=noether`, the relevant failure modes are documented in [noether's `when-things-go-wrong` page](https://alpibrusl.github.io/noether/tutorial/when-things-go-wrong/).

---

## The `.agentspec/records/` trail is your friend

Even for a failed run, the record exists and tells you *when* it failed:

```bash
$ agentspec records show <run-id>
{
  "exit_code": 3,
  "outcome": "runtime_error",
  "duration_ms": 4210,
  "started_at": "…",
  …
}
```

`duration_ms` especially — a 4-second exit usually means the runtime CLI talked to a provider and got a real error back. A 15ms exit means the sandbox refused before the CLI even loaded.

---

## Diagnosis recipes

### "My agent runs locally but not in CI"

Most common: CI containers lack bwrap. Either install it (`apt install bubblewrap`) or set `AGENTSPEC_ISOLATION=none` in the CI env **if** the manifest's `trust:` is permissive. For tight-trust manifests, install bwrap — downgrading production's posture is rarely the right move.

### "The resolver picks the wrong model"

`agentspec resolve --verbose` shows the decision chain. Usually: you set `OPENAI_API_KEY` but want Gemini, so the resolver picks codex-cli first. Reorder `preferred:` explicitly, or unset the env var that's tricking the match.

### "Records say success but the agent didn't do the thing"

Records only capture exit code and duration — they don't inspect the LLM's output. If the agent ran and exited 0 but produced garbage, the record can't tell you that. Add `observability.trace: true` to the manifest and pair with the runtime's own logging (Claude Code's traces, Gemini CLI's `--verbose`, etc.).

### "Pull works but push doesn't"

The registry requires `X-API-Key` for pushes; pulls are public. If you're seeing `401` on push, check `AGENTSPEC_API_KEYS` on the server or `--api-key` on the client. Cross-tenant pushes (`alice/…` with bob's key) also return 401 by design.

---

## What to read next

- **[Concepts](concepts.md)** — the mental model the error messages refer to.
- **[Full pipeline walkthrough](full-pipeline.md)** — hands-on examples of the commands covered here.
- **[Agent playbook: debug-a-failed-run](../agents/debug-a-failed-run.md)** — dense reference version of this page, for agents.
