# Full pipeline: manifest → run → record → lock → isolated re-run

`getting-started/first-agent.md` shows you the 90-second version — write a manifest, run it. This page walks the full production-shaped pipeline: every feature that turns "I ran an agent once" into "a team can ship this agent to production with an audit trail."

Nothing here requires an API key — we use the `test-echo` pseudo-runtime so you can follow along on a fresh machine.

---

## 0. Prerequisites

```bash
pip install agentspec-alpibru
```

For the isolation section, also:

- `bubblewrap` (`apt install bubblewrap` / `brew install bubblewrap` / via Nix).
- Optional: `noether-sandbox` (Linux-only) from [noether v0.7.3+](https://github.com/alpibrusl/noether/releases) — opt-in via `AGENTSPEC_ISOLATION_BACKEND=noether`.

---

## 1. Write the manifest

Create `demo.agent` in a fresh directory:

```yaml
apiVersion: agent/v1
name: demo
version: 0.1.0
description: "End-to-end pipeline walkthrough"

runtime: test-echo
model:
  preferred:
    - test-echo/demo

behavior:
  persona: demo-agent

trust:
  filesystem: none
  network: none
  exec: full

observability:
  trace: true
```

`test-echo` maps to POSIX `echo` — not a real LLM, but it exercises the full resolver → runner → record path.

Validate it:

```bash
$ agentspec validate demo.agent
Valid: demo@0.1.0 (ag1:…)
```

`ag1:…` is the manifest's **content hash** — a fingerprint that changes whenever the manifest changes. Lockfiles pin to it.

---

## 2. Resolve without running

`resolve` shows what `run` *would* do:

```bash
$ agentspec resolve demo.agent
  Runtime:  test-echo
  Model:    test-echo/demo
  Auth:     local socket
  Tools:    none
```

If you're missing the `echo` binary (you're not — every Linux has it), the resolver surfaces that here rather than at run time.

---

## 3. Run it — isolation kicks in automatically

```bash
$ agentspec run demo.agent
  Runtime:  test-echo
  Model:    test-echo/demo
  Auth:     local socket
  Tools:    none

Launching test-echo...
[test-echo] demo@0.1.0
```

Under the hood, `run` did the following:

1. Resolved the plan (step 2).
2. Derived an `IsolationPolicy` from `trust:` — `filesystem: none` → workdir-only RW, `network: none` → network namespace unshared.
3. Wrapped the spawned `echo` in `bwrap --unshare-all --cap-drop ALL …`.
4. Wrote an execution record to `.agentspec/records/<run-id>.json`.

Check the record:

```bash
$ agentspec records list
2026-04-21T10:30:45Z  demo@0.1.0  exit=0  312ms  ag1:…
```

```bash
$ agentspec records show <run-id>
{
  "schema": "agentspec.record/v1",
  "run_id": "01HT…",
  "agent": { "name": "demo", "version": "0.1.0", "hash": "ag1:…" },
  "runtime": "test-echo",
  "started_at": "2026-04-21T10:30:45Z",
  "duration_ms": 312,
  "exit_code": 0,
  "outcome": "success",
  "host": { "os": "linux", "arch": "x86_64", "user": "…" }
}
```

No prompt content, no output, no secrets — records are the *audit trail*, not the transcript.

---

## 4. Pin the plan with a lockfile

A manifest is portable; a *run* should be reproducible. Lock the resolved plan:

```bash
$ agentspec lock demo.agent
Wrote demo.agent.lock
```

```bash
$ cat demo.agent.lock
{
  "schema": "agentspec.lock/v1",
  "manifest": { "hash": "ag1:…", "path": "demo.agent" },
  "resolved": {
    "runtime": "test-echo",
    "model": "test-echo/demo",
    "auth_source": "local socket",
    "tools": [],
    "system_prompt_sha256": "…",
    "host": { "os": "linux", "arch": "x86_64" }
  }
}
```

The system prompt is stored as a sha256 — the lockfile is safe to commit to shared repos even when the prompt contains proprietary persona text.

Now re-run against the lock:

```bash
$ agentspec run demo.agent --lock demo.agent.lock
```

If you edit the manifest (changing the hash), the lock rejects:

```bash
$ agentspec run demo.agent --lock demo.agent.lock
Error: manifest hash ag1:aaaa… does not match lock's recorded hash ag1:bbbb…
  Re-run `agentspec lock demo.agent` if the drift is intentional.
```

That's the point: a drift-catch happens before the subprocess spawns, not after.

---

## 5. Sign the lock for CI

Generate an Ed25519 keypair:

```bash
$ python3 -c "from agentspec.profile.signing import generate_keypair; \
    priv, pub = generate_keypair(); \
    print('AGENTSPEC_SIGNING_KEY='+priv); print('AGENTSPEC_PUBKEY='+pub)"
AGENTSPEC_SIGNING_KEY=abc…
AGENTSPEC_PUBKEY=def…
```

Re-lock with a signing key read from the env (never from a flag — `ps aux` would see it):

```bash
$ export AGENTSPEC_SIGNING_KEY=abc…
$ agentspec lock demo.agent --sign-key-env AGENTSPEC_SIGNING_KEY
Wrote demo.agent.lock (signed)
```

The lock now contains an Ed25519 signature envelope over the `(manifest, resolved)` pair.

Verify it:

```bash
$ agentspec verify-lock demo.agent.lock --pubkey def…
VALID: signature verifies for demo@0.1.0
```

In CI, run with fail-closed verification:

```bash
$ agentspec run demo.agent --lock demo.agent.lock \
    --require-signed --pubkey def…
```

`--require-signed` refuses to run unless the lock is a signed envelope that verifies against the named key. If someone mutates `resolved.runtime` to `malicious-cli` but leaves the manifest hash intact, the signature no longer matches — CI fails before the subprocess spawns.

---

## 6. Switch the isolation backend

By default, `agentspec run` builds the bwrap argv directly. From v0.5.1 onward you can delegate to `noether-sandbox` (same sandbox primitive, one upstream implementation shared with the noether composition engine):

```bash
$ AGENTSPEC_ISOLATION_BACKEND=noether agentspec run demo.agent
```

The output is identical. Under the hood, `agentspec`:

1. Serialises the `IsolationPolicy` to noether's JSON wire format.
2. Writes it to a tmpfile.
3. Spawns `noether-sandbox --policy-file <path> --isolate=bwrap --require-isolation -- echo …`.

If `noether-sandbox` isn't on `PATH`, or if the policy has a shape noether can't yet express (`filesystem: full` — host passthrough), `agentspec` falls back to its direct-bwrap path with a debug log. No crash, no silent loss of isolation.

See [concepts/inheritance.md](../concepts/inheritance.md) for the trust model that drives both backends.

---

## 7. Publish to a registry

Start a local registry:

```bash
$ export AGENTSPEC_API_KEYS="alice:alice-key,bob:bob-key"
$ agentspec registry serve --bind 127.0.0.1:8765 &
```

Push the manifest as `alice`:

```bash
$ agentspec push demo.agent --registry http://127.0.0.1:8765 \
    --api-key alice-key
Pushed demo@0.1.0 → tenant 'alice'
```

Pull it from another machine (or as an anonymous reader — public reads don't need a key):

```bash
$ agentspec pull alice/demo@0.1.0 --registry http://127.0.0.1:8765 \
    --out pulled.agent
Fetched demo@0.1.0 → pulled.agent
```

Tenants are isolated: bob cannot push to `alice/…`, and attempting a cross-tenant push returns `401`. Pulls are public by design (anonymous read matches the "agents are shareable artifacts" thesis).

---

## What you built

In ~50 commands you exercised every load-bearing feature of AgentSpec v0.5+:

| Step | Feature |
|---|---|
| 1 | `.agent` manifest format |
| 2 | Resolver — environment negotiation |
| 3 | Runner + bubblewrap isolation |
| 3 | Execution records |
| 4 | Lockfiles |
| 5 | Ed25519-signed locks for CI |
| 6 | Noether-adapter isolation backend |
| 7 | Multi-tenant registry |

---

## What to read next

- **[When things go wrong](when-things-go-wrong.md)** — reading failures, exit-code contract, common diagnostics.
- **[Multi-runtime guide](../guides/multi-runtime.md)** — one manifest across Claude/Gemini/Ollama/Codex.
- **[Vertex AI routing](../guides/vertex-ai.md)** — running the same manifest in GCP without edits.
- **[Registry guide](../guides/registry.md)** — production deployment patterns.
