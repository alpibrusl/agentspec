# Proposal 001 — Execution Records and (Optional) Lockfile

**Status**: draft for discussion, no code
**Author**: Alfonso Sastre
**Date**: 2026-04-18
**Targets**: v0.5.x

---

## Context

AgentSpec v0.4.1 ships:

- `.agent` manifests (declarative spec)
- Resolver (turns spec into a runtime plan at invocation time)
- Provisioner (materialises native config before spawn)
- Runner (spawns the chosen runtime)
- Registry (push/pull manifests; now multi-tenant)
- Profiles (persistent signed identity accumulated across sprints)

What it does **not** ship:

- **Any after-the-fact evidence of what ran.** When `agentspec run foo.agent` completes, the world has lost the resolved plan, the exact runtime version used, the MCP server versions invoked, and the outcome — unless the operator captured stdout/stderr by hand.
- **Any way to pin a resolved plan for later re-use.** Two machines running the same manifest resolve differently depending on local CLIs, API keys, and model availability. That's fine for interactive use; it breaks every other use case (CI audit, fleet deploys, "ship this agent to a teammate and have it behave").

This is the gap the "Docker of agents" aspiration was trying to close. The prior pressure-test concluded:

- True reproducibility is **not possible**. LLMs aren't deterministic, model weights aren't pinnable, tool state (web search results, filesystems) drifts underneath.
- What is achievable: **pin the setup** (versions of everything AgentSpec controls) plus **record the outcome** (tamper-evident log of what was observed).

Position this work as **attestation**, not **reproducibility**. Be honest about what bytes are signed and what inferences the signature actually supports.

---

## Goals

1. **Attestation over reproducibility.** Don't promise re-running will produce identical outputs. Do promise records of what ran, when, against what.
2. **Reuse existing crypto.** Ed25519 via PyNaCl, canonical JSON. Same envelope as signed profiles. No new primitives.
3. **Opt-in privacy.** No prompt content, no outputs, no secrets in the record by default. Fields that could leak live behind explicit flags or manifest-level policy.
4. **Small surface.** Two concepts (lock, record), one envelope (reuse profile signing), two CLI verbs (`lock`, `records`). No policy engine in v1.
5. **Offline-friendly.** Records are files on disk. A registry can mirror them later; a registry is not required.
6. **Compose with profiles.** An execution record is a natural input to a portfolio entry — one honest aggregation path.

## Non-goals

- **Byte-for-byte reproducibility of model output.** Explicitly not promised.
- **Sandbox enforcement.** Records describe what happened; they don't prevent anything.
- **Universal verifier.** We provide signing + canonical serialisation; who verifies, against which pubkeys, for what purpose is a deployment decision.
- **Streaming / chunked journal.** One record per run, written at completion.
- **Record-based auto-retry or policy gating.** Out of scope.

---

## Proposal: Two Concepts

### Concept 1 — `agentspec.lock` (pre-execution frozen setup)

Produced by `agentspec lock <manifest>` or `agentspec run --emit-lock`. Captures the **resolver output** plus detected environment versions, so another machine can reproduce the *setup* — not the outputs.

Canonical JSON, example:

```jsonc
{
  "schema": "agentspec.lock/v1",
  "manifest": {
    "hash": "ag1:abc123…",
    "name": "deep-researcher",
    "version": "1.0.0"
  },
  "resolved": {
    "runtime": "claude-code",
    "runtime_version": "0.6.2",
    "model": "claude/claude-sonnet-4-6",
    "tools": ["web-search", "cite-sources"],
    "mcp_servers": [
      { "name": "brave-mcp", "version": "0.2.1", "hash": "sha256:…" }
    ],
    "auth_source": "env.ANTHROPIC_API_KEY",
    "system_prompt_hash": "sha256:…"
  },
  "host": {
    "os": "linux-x86_64",
    "agentspec_version": "0.5.0"
  },
  "generated_at": "2026-04-18T14:03:00Z",
  "warnings": []
}
```

**What this pins**:

- Runtime CLI version (when the CLI reports one).
- MCP server versions / hashes (when declarable).
- System prompt hash (detects silent prompt drift — child manifest changes, trait edits, SOUL.md rewrites).
- Resolver decisions (so divergence between machines is visible via `diff lock1 lock2`).

**What this does not pin**:

- Model weights / provider behaviour (not available via any public API).
- Tool state (a web-search index today ≠ tomorrow).
- The *contents* of the system prompt (hash only — full prompts may include private identity or third-party data).

Signing is optional. When signed, reuse the profile's Ed25519 envelope.

CLI:

```bash
agentspec lock foo.agent [--out foo.agent.lock] [--sign]
agentspec verify-lock foo.agent.lock --pubkey <hex>
agentspec run foo.agent --lock foo.agent.lock   # run from lock; fail fast
                                                # if local env cannot satisfy it
```

### Concept 2 — Execution Record (post-execution tamper-evident log)

Written automatically at end of `agentspec run` unless `--no-record`. One JSON file per run under `.agentspec/records/<run-id>.json`.

Canonical JSON, example:

```jsonc
{
  "schema": "agentspec.record/v1",
  "run_id": "01JR8F3…",                // ULID — sortable, no PII
  "manifest_hash": "ag1:abc123…",
  "lock_hash": "sha256:…",             // null if run without a lock
  "started_at": "2026-04-18T14:03:00Z",
  "ended_at":   "2026-04-18T14:07:42Z",
  "duration_s": 282.13,
  "runtime": "claude-code",
  "runtime_version": "0.6.2",
  "model": "claude/claude-sonnet-4-6",
  "exit_code": 0,
  "outcome": "success",                 // success | failure | aborted | timeout
  "warnings": [],

  // Opt-in fields — declared in the manifest or via CLI flag:
  "token_usage": { "input": 12450, "output": 3120 },
  "tool_calls":  { "web-search": 7, "cite-sources": 3 },
  "output_digest": "sha256:…"          // digest of a stable runtime-specific
                                       // summary, never raw output
}
```

**Never in the record**:

- Prompt content.
- Tool-call arguments or results.
- Stdout / stderr content.
- API keys, auth tokens, or any secret values.

**Opt-in only** (default off):

- `token_usage` — requires fetching provider billing data; may leak pricing/usage signals.
- `output_digest` — requires defining "the output" per runtime; CLI-specific.
- `tool_calls` — fine-grained counts; generally safe, but still opt-in so operators don't surprise themselves.

Signing:

- Every record is signed at write time with the profile's Ed25519 key, when a profile exists for this agent. Envelope identical to profile memories.
- Records without a profile are unsigned plain JSON — the run still produced evidence, just not attested.

CLI:

```bash
agentspec records list [--agent <hash>] [--since 2026-04-01]
agentspec records show <run-id>
agentspec records verify <run-id> --pubkey <hex>
agentspec records export <run-id> --to <file>
```

### Relationship with profiles

An execution record is the raw, per-run log. A portfolio entry is the aggregated, human-annotated summary. Records feed retros:

```bash
agentspec run foo.agent              # writes record r1
# ... more runs ...
agentspec profile retro foo.agent \
    --records r1,r2,r3 \
    --feedback retro.yaml
# → ingests three records into one portfolio entry
```

Records and portfolio entries remain separate artifacts, linked by record ID. Records are the evidence; portfolio entries are the claim built on top of the evidence.

---

## Envelope & canonicalization

Reuse `agentspec.profile.signing` verbatim:

- Same `canonical_json` (sort keys, no whitespace).
- Same Ed25519 algorithm, same PyNaCl dependency.
- Same envelope shape: `{ payload, algorithm, signature, public_key }`.
- Same verifier pattern (`verify_memory` / `verify_portfolio_entry`).

If profile signing is ever audited, the audit covers lock and record signing for free.

---

## Open questions

Decisions I want your input on before writing code.

1. **Lockfile: optional or required?** My default is optional. Useful for CI and team hand-off, adds friction interactively. Confirm?
2. **Record storage**: local disk (`.agentspec/records/`) only in v1, or also mirror to the registry? My preference is **disk-only in v1** — registry mirroring needs a privacy review and opt-in flow that's not worth building yet.
3. **Opt-in field declaration**: CLI flags (`--record-usage`, `--record-tools`) or manifest policy (`observability.record: [usage, tools, output_digest]`)? Manifest feels more AgentSpec-y — per-agent policy, not per-invocation toggle. Prefer manifest?
4. **`output_digest` semantics**: each runtime produces different "output" (files written, git diffs, chat transcripts). Options:
   - (a) Skip in v1. Punt to v2 when we know what we want.
   - (b) Define a `Runtime.digest()` hook each runner fills in; start with git-diff digest for coding runtimes, empty for others.
   - My pick: (a) — avoid a half-baked definition.
5. **Run IDs**: ULID (sortable, no PII, monotonic). Alternatives: UUIDv7 (similar), content hash (nice but awkward — can't assign until `ended_at`). Pick ULID?
6. **Record retention**: auto-prune? My default is **no** — disk is cheap, records are ~1 KB each, accidental deletion is worse than clutter. Document a manual cleanup recipe.
7. **Naming**: `agentspec.lock` borrows Docker's word but means something softer. Alternatives: `agentspec.plan.json`, `agentspec.pin`, `agentspec.fix`. Keep `.lock` because users expect the conceptual shape, or rename to something less misleading?
8. **Relationship to the existing resolver output**: the resolver already produces `ResolvedPlan`. Is the lockfile just "ResolvedPlan + host info + hash + signature," or do we want a distinct schema to let the two evolve independently? I lean toward **distinct schema** — lockfiles are artifacts, ResolvedPlan is a runtime object.

---

## What NOT to build in v1

- **No reproducibility claims.** Docs must read "records attest; they don't replay."
- **No raw-output capture.** Digest only, opt-in, and only when the runtime knows how to produce a stable one.
- **No policy engine or CI plugin.** Verification is: "does this signature check out against this pubkey?" — full stop.
- **No registry-side record storage.** Private by default, v2 decision.
- **No cross-run diffing.** Records are independent; diffing is a tool someone else can build on top.
- **No implicit signing without a profile.** Records-without-profiles are unsigned plain JSON — they're still evidence, just not attested. Forcing a profile for every `run` would be a major UX regression.

---

## Rollout

- **v0.5.0**: introduce lock CLI and record emission. Default: records written to `.agentspec/records/`, locks emitted only on explicit `agentspec lock` or `agentspec run --emit-lock`.
- **v0.5.x**: register lock + record formats as Noether stages when the Noether extension is active, so pipelines can produce them as outputs.
- **v0.6.0**: consider `--lock <file>` on `agentspec run` as a hard requirement in CI mode (fail fast on env mismatch).
- **v0.7.0** (tentative): registry-side record storage with explicit privacy review and opt-in.

---

## Alternatives considered

1. **Docker-style image layer** — package agent + runtime + tools into one artifact. Rejected: runtimes are closed-source CLIs you can't redistribute; model weights don't travel. Ends up as a Dockerfile for the host CLI, which is out of scope for AgentSpec.
2. **On-chain record** — sign records to a public chain for decentralised verification. Rejected: privacy, cost, who-runs-the-chain, and the adoption path is worse than the problem.
3. **No record at all, just stdout logs** — current state. Works interactively, fails every other use case: CI audit, sprint retros, portfolio validation.
4. **Record full prompts and outputs** — rejected: privacy tarpit. An opt-in digest of a runtime-defined stable summary is the honest middle.

---

## Success criteria

- A team running `agentspec run` in CI can commit `.agentspec/records/*.json` to git and track outcome trends over time without hand-rolled parsing.
- A registry-pulled agent run on a fresh machine can produce a lock, and a human can diff two locks from two hosts to see exactly why the agent resolves differently.
- Profile portfolio entries can be generated from N records plus a retro step, with the signed audit trail intact end-to-end.
- Nobody reads the docs and comes away thinking "lock" means "identical outputs." The honest framing leads every page.

---

## What this doesn't replace

- **Trust-restricting inheritance** remains the load-bearing security property. Records attest that the trust model wasn't bypassed at spawn time; they don't enforce it. Enforcement stays in the merger + provisioner.
- **Multi-tenant registry auth** (PR #13) controls who can push/pull manifests. Records and locks are orthogonal — neither replaces tenant isolation.
- **Profiles and signed portfolios** continue to be the "verifiable CV" story. Records are the evidence layer *under* portfolios, not a replacement for them.

Think of the stack as:

```
  manifest         ← what I want
    ↓
  resolved plan    ← what I'll run here
    ↓
  lock             ← the plan, pinned as an artifact (optional, pre-run)
    ↓
  record           ← what actually happened (auto, post-run)
    ↓
  portfolio entry  ← human-reviewed summary of many records (existing)
```

Each layer is smaller, more concrete, and more signed than the one above it.
