# Core concepts: a 5-minute mental model

Before the walkthrough, a short tour of the four ideas AgentSpec is built on. Every page of docs after this one assumes you've read this one.

If you've used Docker, `.envrc`, Nix, or a typed configuration language, most of this will feel familiar. If you haven't, the analogies still work — read past them.

---

## 1. A `.agent` file declares, it doesn't install

An `.agent` file (YAML) describes what an agent *is* — its persona, skills, preferred models, trust posture, observability. It does not pin a specific runtime, install a CLI, or ship model weights.

```yaml
apiVersion: agent/v1
name: researcher
version: 1.0.0
model:
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b
skills: [web-search, cite-sources]
trust:
  filesystem: none
  network: allowed
```

The same file runs on your laptop with Claude, in CI with Gemini, and on a GCP VM routing through Vertex AI. What changes is the environment around it — not the manifest.

> **Why this matters.** You can publish a manifest to a registry, hand it to a teammate, and they run *the same agent* even though their machine has different tools installed. Portability is the core value; the YAML shape is just how we get there.

See [concepts/format.md](../concepts/format.md) for the full schema.

---

## 2. Resolution is environment negotiation

When you run `agentspec run researcher.agent`, AgentSpec's **resolver** picks concrete values for each declared preference:

1. **Runtime** — which CLI will execute the agent? The resolver checks `PATH` (and delegates to `llm-here` when installed) for `claude-code`, `gemini-cli`, `cursor-cli`, `opencode`, and friends.
2. **Model** — from the `preferred` list, the resolver takes the first provider whose CLI is present *and* whose auth is available in the environment (`ANTHROPIC_API_KEY`, Vertex ADC, etc.).
3. **Tools** — abstract skills (`web-search`) map to concrete MCP servers (`brave-mcp`, `arxiv-mcp`) installed locally. Missing tools surface as warnings, not errors.
4. **System prompt** — composed from the manifest's `persona`, `traits`, `rules`, and an optional `soul` Markdown file.

```bash
$ agentspec resolve researcher.agent
  Runtime:  claude-code
  Model:    claude/claude-sonnet-4-6
  Auth:     env.ANTHROPIC_API_KEY
  Tools:    brave-mcp, arxiv-mcp
```

> **Why this matters.** The manifest is the same across environments; the resolver is the piece that adapts. When you move from Anthropic direct to Vertex AI, you don't edit the manifest — you set `GOOGLE_CLOUD_PROJECT` and the resolver routes.

See [concepts/resolver.md](../concepts/resolver.md).

---

## 3. Trust is declared, enforced at the sandbox boundary

Every manifest carries a `trust` block declaring what the agent is allowed to touch:

```yaml
trust:
  filesystem: none       # workdir-only RW (other modes: read-only, scoped, full)
  network: none          # or: scoped, allowed
  exec: full             # or: none (seccomp-filtered, v0.8+)
```

At runtime, `agentspec run` wraps the spawned CLI in a [bubblewrap](https://github.com/containers/bubblewrap) sandbox whose bind mounts, network namespace, and capability set are derived from this block. `filesystem: none` means the agent sees only its workdir; `network: none` unshares the network namespace so DNS doesn't even resolve.

```
trust.filesystem = none         →  bwrap --unshare-all --cap-drop ALL
trust.network = none            →  (no --share-net)
trust.filesystem = scoped       →  --bind <workdir> <workdir>
                                   --bind <scope-path> <scope-path>
```

Opt out with `--via=none --unsafe-no-isolation` when you trust the code and need host passthrough. Tight manifests (non-permissive trust) **refuse** to run unsandboxed without the explicit flag.

> **Why this matters.** The declaration lives in the manifest, not the CLI invocation — so a reviewer reading the `.agent` file knows exactly what this agent can do. "I said `filesystem: none`" is enforced mechanically.

See [concepts/inheritance.md](../concepts/inheritance.md) for the trust model and how children can only restrict, never widen, a parent's trust.

---

## 4. Two separate boundaries: reproducibility vs. isolation

AgentSpec pins two different things that people often confuse:

| Boundary | What it pins | How |
|---|---|---|
| **Reproducibility of the plan** | Runtime, model, tools, sha256 of the system prompt, host info | **`agentspec.lock`** — resolve once, capture the choices, ship the lockfile with your CI config |
| **Isolation of the run** | Filesystem, network, capabilities, UID | **bubblewrap** at runtime, derived from `trust:` |

A lockfile guarantees the *same plan* resolves on every re-run. It does **not** make the LLM's *output* deterministic (LLMs aren't) — it makes the *setup* deterministic. That's enough to build reproducible pipelines on top of non-reproducible model behaviour.

```bash
$ agentspec lock researcher.agent --sign-key-env AGENTSPEC_SIGNING_KEY
$ agentspec run researcher.agent --lock researcher.agent.lock \
    --require-signed --pubkey $AGENTSPEC_PUBKEY
```

`--require-signed` means CI refuses to run unless the lockfile's Ed25519 signature verifies against a trusted key. The signed lockfile + the manifest is the **attestation**: this plan came from this author, this host, this moment.

See [concepts/format.md#lockfiles](../concepts/format.md).

---

## 5. Every run writes an execution record

`agentspec run` writes a tamper-evident record to `<workdir>/.agentspec/records/<run-id>.json` capturing the manifest hash, runtime, duration, exit code, and outcome. Records never contain prompt content, model output, or secrets — they're the *audit trail* of what happened, not the transcript.

```bash
$ agentspec records list
2026-04-21T10:30Z  researcher@1.0.0      exit=0  312ms
2026-04-21T10:28Z  legal-reviewer@2.1.0  exit=3  4.2s
```

Pair with `agentspec records verify --pubkey <hex>` in CI to fail when the record chain has been tampered with.

---

## What to read next

- **[Full pipeline walkthrough](full-pipeline.md)** — manifest → run → record → lock → isolated re-run.
- **[When things go wrong](when-things-go-wrong.md)** — reading `agentspec` failures.
- **[Your first agent](../getting-started/first-agent.md)** — minimal hands-on.
- **[.agent format reference](../concepts/format.md)** — the full schema.
