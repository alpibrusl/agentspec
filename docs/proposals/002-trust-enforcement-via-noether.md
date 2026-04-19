# Proposal 002 — Trust Enforcement via Noether Delegation

**Status**: Phase 1 shipped as direct bubblewrap ([#17](https://github.com/alpibrusl/agentspec/pull/17)); Phase 2 path set to `noether-isolation` library export.
**Author**: Alfonso Sastre
**Date**: 2026-04-18 (proposal), 2026-04-19 (Phase 1 shipped + Phase 2 direction set after [noether#36](https://github.com/alpibrusl/noether/issues/36))
**Targets**: v0.6.x (Phase 1 — direct bubblewrap), v0.7.x (Phase 2 — `noether-isolation` adapter)
**Depends on**: bubblewrap (`bwrap`) on `PATH` today; [`noether-isolation`](https://github.com/alpibrusl/noether/issues/36) crate for Phase 2

---

## Status (2026-04-19)

### Phase 1 — shipped as direct bubblewrap

Verification against noether on 2026-04-19 surfaced a gap: `noether
run` only executes Lagrange composition graphs, not arbitrary external
commands. Wrapping a runtime CLI via the `spawn_process` stdlib stage
is technically possible but couples agentspec tightly to noether's
graph schema and adds per-runtime integration code.

Phase 1 therefore ships as **direct bubblewrap wrapping in agentspec**
([PR #17](https://github.com/alpibrusl/agentspec/pull/17)), ported
from the same design noether's PR #34 uses for stage isolation. The
`IsolationPolicy` layer is deliberately decoupled from the rendering
step so a future adapter can replace the renderer without touching
the mapping.

### Phase 2 — `noether-isolation` library export

After discussion on [noether#36](https://github.com/alpibrusl/noether/issues/36),
the delegation path for Phase 2 is **library export**, not a new
`noether` CLI subcommand.

- Noether's maintainer pushed back on `noether run-external`: it
  would muddy the "verified composition platform" identity. Users
  would reasonably expect traces, content addressing, registry
  entries, and `noether trace <id>` replay to work; we'd be
  committing to building those or explaining why a Noether command
  intentionally doesn't have them. The `--effects '{...}'` JSON blob
  was also flagged as a code smell (real flags or don't ship the CLI
  form).
- Agreed path: when noether's PR #34 merges, the
  `crates/noether-engine/src/executor/isolation.rs` module is
  extracted into a standalone **`noether-isolation`** crate plus a
  thin **`noether-sandbox`** binary that takes an effect spec and
  argv on stdin and execs under bubblewrap. Targeting noether
  v0.7.1.
- AgentSpec's Python runner calls `noether-sandbox` the same way it
  currently calls `bwrap` — ~20 lines to change in
  `build_bwrap_argv`. The existing `IsolationPolicy` layer is shaped
  for exactly this: Phase 2 becomes a `NoetherIsolationAdapter`
  renderer alongside (eventually replacing) the direct-bwrap
  renderer.
- Vocabulary mapping stays in agentspec: `trust → EffectSet →
  IsolationPolicy`. Noether owns the policy *mechanism*; agentspec
  owns the *mapping*; and that boundary is right.

Install-friction options for the Phase 2 rollout (all tractable,
none blocking):

1. **Preferred**: `pip install agentspec[noether-isolation]` extra
   pulls `noether-sandbox` as a binary dependency. The extra name
   tells users they're opting into the Rust audit surface
   (`noether-sandbox` is written in Rust, so security auditors
   should review the `noether-isolation` crate alongside agentspec).
2. `maturin` / `cibuildwheel` bundles `noether-sandbox` into the
   agentspec wheel per-platform. Self-contained but CI-expensive.
3. Separate install (`cargo install noether-sandbox`), agentspec
   auto-detects the same way it detects `bwrap` today.

When `noether-isolation` is released, we add the adapter and either
default to it when available or make it opt-in — deferring that
choice to the migration PR. During the transition, `--via=bwrap`
keeps working; the adapter is additive, not a replacement on day
one.

### What the rest of this document covers

The `trust → effect` mapping, CLI surface, degradation behaviour,
and open questions below apply to both Phase 1 and Phase 2 — the
adapter swap is a renderer change, not a schema change, so
everything downstream stays valid.

---

## Context

AgentSpec today declares trust **intent** and enforces it **at parse time**:

- The manifest's `trust` block states what a child agent may do (`filesystem: readonly`, `network: deny`, `exec: none`).
- The inheritance merger guarantees a child cannot widen a parent's trust.

What it does **not** do:

- **Enforce that intent at run time.** The runner spawns the chosen CLI as a normal subprocess with the invoking user's full privileges. A `trust: none` agent and a `trust: full` agent behave identically at the process level.

`SECURITY.md` is honest about this:

> It does not sandbox the spawned CLI. The subprocess runs with the privileges of the invoking user.

For v0.4.x, this was a defensible alpha compromise — the point was to get the declarative layer right first. For the "Docker of agents" direction, the gap stops being defensible. Pulling `ag1:unknown-author` from a shared registry and running it on a laptop should not yield a process that can `rm -rf ~/.ssh` regardless of what the manifest declared.

## The opportunity

Sibling project **noether** (v0.7) ships production-grade stage execution isolation:

- `IsolationBackend::Bwrap` (bubblewrap) today — Linux, stable, ~30–80 ms wrap overhead.
- `IsolationBackend::Native` (namespaces + Landlock + seccomp) in v0.8 — ~3–8 ms, zero external dep.
- Policy derived from a stage's `EffectSet` (filesystem/network/exec + capabilities).
- Threat model documented with layered defence tables.
- Graceful fallback: auto-detect, warn when absent, explicit `--unsafe-no-isolation` flag.

The `EffectSet` axes (read/write/network/exec) are the same three axes AgentSpec already exposes via `TrustSpec`. Mapping is straightforward. The question is whether AgentSpec owns a sandbox implementation or delegates.

---

## Goals

1. **Enforce what the manifest declares.** A `trust: none / network: deny` agent must not be able to read `~/.ssh/id_rsa` or dial arbitrary URLs — regardless of the CLI's own behaviour.
2. **Don't duplicate noether's work.** Bubblewrap wrapping + Landlock policy is already well-built in Rust. AgentSpec is Python. Rewriting in Python would be strictly worse.
3. **Keep AgentSpec's scope narrow.** Agentspec declares; noether enforces. Same division of labour we used for "Docker of agents" narrowing.
4. **Graceful degradation.** Users without noether installed still get something useful; users whose manifests require isolation get a clear error instead of silent unsandboxed execution.
5. **No cross-project lock-in.** AgentSpec remains usable without noether — just without enforcement — for people who don't want the Rust dependency.

## Non-goals

- **Writing a sandbox in AgentSpec.** Even a "lite" version.
- **Cross-platform sandbox parity.** bwrap is Linux-only; macOS/Windows get a warning and the legacy path. Matching Linux on other OSes is a noether concern, not agentspec's.
- **Fine-grained capability shaping.** AgentSpec exposes three axes (fs/net/exec); noether's full capability matrix is not surfaced in the manifest. Advanced users who need that go to noether directly.
- **Replacing the existing trust merger.** The parse-time invariant still holds. Enforcement is additive.

---

## Proposal

### Division of labour

```
┌────────────────────────┐
│   AgentSpec manifest   │
│   trust: {fs, net, ex} │
└──────────┬─────────────┘
           │  (agentspec maps)
           ▼
┌────────────────────────┐
│   Noether EffectSet    │
│   {Read, Write, Net…}  │
└──────────┬─────────────┘
           │  (noether enforces)
           ▼
┌────────────────────────┐
│  IsolationPolicy +     │
│  Bwrap / Native runner │
└────────────────────────┘
```

AgentSpec owns the mapping table. Noether owns the enforcement mechanism. When noether's v0.8 native backend ships, agentspec transparently benefits — no agentspec changes required.

### Trust → EffectSet mapping

| `trust.filesystem` | Noether effects | IsolationPolicy shape |
|---|---|---|
| `none` | `{}` | RO bind `/nix/store` only; `/work` tmpdir RW. Host HOME unreachable. |
| `readonly` | `{Read}` | RO binds for each path in `scope`; `/work` tmpdir RW. |
| `scoped` | `{Read, Write}` (scoped) | RW bind mount for each path in `scope`; everything else RO or absent. |
| `readwrite` | `{Read, Write}` (host) | Inherit host rootfs RW. Effectively no isolation — warn loudly. |

| `trust.network` | Noether effects | IsolationPolicy shape |
|---|---|---|
| `none` / `deny` | `{}` | Fresh empty network namespace. No egress possible. |
| `scoped` | `{Network}` with filter | Pass-through netns + egress filter (see v0.8 note below). |
| `allowed` | `{Network}` unfiltered | Inherit host netns. |

| `trust.exec` | Noether effects | IsolationPolicy shape |
|---|---|---|
| `none` | `{}` | seccomp `execve` blocked. |
| `sandboxed` | `{Exec}` (bounded) | `execve` allowed only for binaries under allowlist paths. |
| `full` | `{Exec}` (unbounded) | `execve` unrestricted. |

The mapping itself is a Python function `agentspec.runner.isolation.to_effects(trust) -> EffectSet` that lives in AgentSpec. Noether consumes the resulting JSON via its existing stage-effect parser.

Edge cases:

- **`trust.network: scoped` with a host allowlist** — noether v0.8's egress filter is the target; v0.7 bwrap can only offer all-or-nothing. In v0.7 mode, `scoped` with any non-empty allowlist is treated as `allowed` with a warning.
- **`trust.exec: sandboxed` with `scope` paths** — maps to bwrap `--dev-bind` with limited execution paths.

### CLI surface

Three new flags on `agentspec run`:

```bash
agentspec run foo.agent                       # auto-detect: use noether if installed
agentspec run foo.agent --via noether         # explicit; fail if not installed
agentspec run foo.agent --unsafe-no-isolation # explicit opt-out (warns)
```

Default behaviour with **auto-detect**:

1. If `noether` binary is on `PATH`, use it.
2. If not on `PATH` **and** the manifest declares any non-trivial trust constraint (`filesystem != readwrite` OR `network != allowed` OR `exec != full`): **fail** with a clear message pointing at install instructions.
3. If not on `PATH` **and** the manifest is fully permissive: proceed unsandboxed with a one-time warning (identical to the current behaviour).

This matches how noether already handles `--isolate auto`: use the best backend available; be loud when constraints can't be met.

Environment variable precedence:

- `AGENTSPEC_RUNNER=noether` / `AGENTSPEC_RUNNER=legacy` — deployment-wide default.
- CLI flag overrides env.

### Runner refactor sketch

```python
# src/agentspec/runner/runner.py  (pseudo-diff)

def execute(plan, manifest, input_text):
    backend = _select_backend(plan, manifest)  # NEW
    if backend == "noether":
        return _execute_via_noether(plan, manifest, input_text)
    return _execute_legacy(plan, manifest, input_text)

def _execute_via_noether(plan, manifest, input_text):
    effects = isolation.to_effects(manifest.trust)  # NEW module
    cmd = ["noether", "run",
           "--isolate", "auto",
           "--effects", json.dumps(effects),
           "--", *build_command(plan)]
    return subprocess.run(cmd, ...)
```

`isolation.to_effects()` is the only new agentspec module. Everything else is argument-passing.

### Provisioner interaction

The provisioner today writes `CLAUDE.md`, `.mcp.json`, etc. to `workdir` **before** the subprocess spawns. Under sandboxed execution, `workdir` is mounted into the sandbox as the RW work bind — so the files are visible to the runtime. No provisioner changes required as long as we pick the right bind path.

One gotcha: when MCP servers are installed via `provision_install()` (pip/npm/cargo), those installs currently happen outside the sandbox. We either run them inside too (safer; slower because package managers don't cache well in fresh namespaces) or treat install-time as "trusted host" and document that declared `requires` lists run unisolated. I lean toward **trusted install-time** for v1 (document clearly, sandbox only the run step) and revisit for v2.

---

## Open questions

1. **Default behaviour when noether is installed but the manifest is permissive.** Opt-in (current legacy path), or auto-use noether for consistency even when no constraint is declared? My default: **auto-use** — consistency matters more than saving 30 ms on unconstrained runs.

2. **Fail-fast vs warn-and-degrade when noether is missing.** If the manifest requires non-trivial trust and noether isn't available, fail or just warn? My default: **fail**. A silently degraded run is worse than a missing tool.

3. **Packaging.** Ship a Python `agentspec[isolation]` extra that pins a noether version? Or leave it as a "install separately" story? Since noether is a Rust binary not a Python package, the extra would install nothing — just be a marker. My default: **don't ship the extra**; document the dependency in SECURITY.md and the runner docs.

4. **Non-Linux hosts.** macOS/Windows users get warned and fall through to legacy today. Do we special-case macOS eventually (`sandbox-exec`)? My default: **punt to noether** — if noether ships a macOS backend, agentspec gets it for free.

5. **`trust.network: scoped` with a host allowlist in v0.7 mode.** Treat as `allowed` with a warning? Or fail? My default: **warn and treat as `allowed`** — closest to declared intent and matches noether's "best available" philosophy.

6. **`provision_install` inside or outside the sandbox?** My default: **outside** in v1 (document as "install-time trust required"); inside in v2 when we can cache sensibly.

7. **Who owns the trust→effect mapping?** AgentSpec or noether? My default: **AgentSpec** — it's specific to our trust vocabulary and evolves with our schema. Noether's job is to consume a generic EffectSet; it shouldn't know `TrustSpec`.

8. **What about the currently-existing `agentspec.runner` path?** Do we keep it as `--unsafe-no-isolation`, or deprecate it over time? My default: **keep indefinitely** as the opt-out — non-Linux hosts and air-gapped environments need it; noise is bounded by the one-time warning.

9. **CLI proprietary binaries under bwrap.** claude-code, gemini-cli, cursor-agent are closed-source. They may do things bwrap doesn't love (spawn helpers, open netlinks). Do we need a per-runtime compatibility matrix, or start open and fix issues as they surface? My default: **start open**; add a `known_bwrap_incompat` list in the runner module with runtime-specific workarounds as needed.

---

## Rollout

- **v0.5.x** (concurrent): records from Proposal 001 land. No isolation yet.
- **v0.6.0** (Phase 1): ship `agentspec.runner.isolation` with direct bwrap rendering. `--via auto|bwrap|none` CLI flag, `--unsafe-no-isolation` opt-out, `AGENTSPEC_ISOLATION` env fallback. Manifests with tight trust fail closed when bwrap is missing; permissive manifests warn.
- **v0.7.x** (Phase 2): add `NoetherIsolationAdapter` as a second renderer behind the same `IsolationPolicy` layer. Ships after noether v0.7.1 exposes the `noether-isolation` crate + `noether-sandbox` binary per [noether#36](https://github.com/alpibrusl/noether/issues/36). Default backend choice (direct vs adapter) deferred to the migration PR — likely adapter-preferred with direct as a fallback.
- **v0.8.x**: when noether's Phase 2 native backend (namespaces + Landlock + seccomp, no external binary) lands upstream, agentspec picks it up transparently via the adapter. No agentspec changes required.

## Alternatives considered

1. **Write a Python sandbox in AgentSpec.** Rejected: duplicates noether, worse security (Python GIL-bound; fewer contributors reviewing sandbox code; no Landlock/seccomp bindings in stable Python stdlib).
2. **Use subprocess's `preexec_fn` to call `setrlimit`/`prctl` directly.** Rejected: partial isolation at best, no filesystem or network containment, complex to audit.
3. **Use Docker/Podman as the sandbox.** Rejected: too heavy (~300 MB images), adds a hard dependency on a container runtime, and fights the `$EDITOR`/terminal-aware CLIs that need to see stdin/tty.
4. **Leave it out of scope.** Rejected: "Docker of agents" without runtime isolation is a hollow pitch. Status quo (SECURITY.md disclaim) was acceptable for alpha; not for the direction we're moving.
5. **Own trust→effect mapping in noether.** Rejected: leaks AgentSpec's schema into noether. The mapping belongs with the schema.

---

## Success criteria

- A user can `agentspec run` an unknown agent from the registry and trust that its declared `trust: none` actually means the subprocess can't touch `~/.ssh` or `~/.aws`.
- The `agentspec run` UX is unchanged for permissive agents on machines with noether — it just becomes safer.
- A user without noether installed gets either (a) a working unsandboxed run with a warning (permissive manifests) or (b) a clear install prompt (constrained manifests). Never silent degradation.
- No Python sandbox code in AgentSpec. Zero lines.
- When noether ships native namespaces (v0.8), agentspec users benefit without upgrading agentspec.

---

## Relationship with other work

- **Proposal 001 (records)**: complementary, not dependent. An execution record captures *which* isolation backend was used and *what* policy was applied — useful evidence when disputing "did the sandbox actually contain this run?"
- **Multi-tenant registry (PR #13)**: orthogonal. Tenant auth controls who can publish; isolation controls what a running agent can reach. Both needed for a real "Docker of agents."
- **Trust-restricting merger**: still the load-bearing invariant at parse time. Isolation is the run-time complement. Keep both.
- **caloron-noether**: already uses noether for composition. If we delegate isolation to noether, caloron-noether gets it consistent across both layers — one sandbox semantics, not two.

## What this doesn't fix

- **Model provider trust.** The sandbox contains the local subprocess. It does not prevent the model from generating harmful text sent back to you. That's a different problem (output filtering, tool-call allowlists, etc.) and out of scope.
- **Supply-chain trust of the CLI binaries themselves.** bwrap can't help if the Claude Code binary you downloaded was tampered with. Signature verification of CLIs is a runtime concern upstream.
- **Side-channel leaks.** A sandboxed subprocess can still observe timing, CPU contention, and (on some kernels) other information. Full mitigation requires a different threat model.
