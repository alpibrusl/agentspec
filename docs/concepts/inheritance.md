# Inheritance & Trust

Agents extend other agents with explicit, enforced merge semantics. The trust-restrict invariant is **hardcoded** — children can never escalate permissions.

## Basic inheritance

```yaml
# legal-researcher.agent
apiVersion: agent/v1
name: legal-researcher
version: 1.0.0

base: ./researcher.agent

merge:
  skills: append      # append | override | restrict
  tools: append
  behavior: override
  trust: restrict     # always restrict (hardcoded)

tools:
  mcp:
    - courtlistener
    - google-scholar

behavior:
  persona: precise-legal-researcher
  traits:
    - cite-everything
    - cite-jurisdiction    # legal-specific
  temperature: 0.1
```

The legal researcher inherits the base researcher's skills, behavior, and trust, then layers on legal-specific tools.

## Merge strategies

### `append` (skills, tools)

Combines parent + child, deduplicating:

```yaml
# parent.skills:  [web-search, summarize]
# child.skills:   [cite-sources, summarize]
# merged:         [web-search, summarize, cite-sources]
```

### `override` (behavior, optionally skills/tools)

Child wins entirely:

```yaml
# parent.behavior.traits: [careful, formal]
# child.behavior.traits:  [creative]
# merged:                 [creative]
```

### `restrict` (skills, tools)

Child can only use a subset of what the parent allows:

```yaml
# parent.skills:  [web-search, code-execution, file-write]
# child.skills:   [web-search, browser]    # tries to add browser
# merged:         [web-search]              # browser dropped — not in parent
```

Useful for sandboxing — an enterprise can publish a base with an allowed-list of skills, and child agents can only choose from that list.

## Trust-restrict invariant

This is the security guarantee. Trust merge is **always** restrictive — hardcoded, can't be changed:

```yaml
# parent.trust:
filesystem: read-only
network: none
exec: none

# child.trust:    (tries to escalate)
filesystem: full
network: allowed
exec: full

# merged.trust:   (clamped to most restrictive)
filesystem: read-only
network: none
exec: none
```

If the child explicitly tries to escalate, the merger raises `TrustEscalationError`:

```python
from agentspec.resolver.merger import resolve_inheritance

try:
    resolved = resolve_inheritance(child_manifest)
except TrustEscalationError as e:
    print(f"Refused: {e}")
```

The trust order:

```
filesystem:  none < read-only < scoped < full
network:     none < scoped < allowed
exec:        none < sandboxed < full
```

Child must be `<=` parent on every dimension.

## Why this matters

In multi-agent systems, you compose agents from base templates. Without enforcement:

- A "research agent" base allows `network: allowed`
- A child "rogue research agent" silently adds `exec: full`
- Now you've got a network-enabled code execution agent in production

With AgentSpec inheritance:

- Trust merge ALWAYS restricts
- Child can't add `exec: full` if parent has `exec: none`
- Enforced at merge time, before resolver, before execution
- Auditable — the merged manifest shows the final trust

## Inheritance chain

```yaml
# claude-noether.agent
base: ./claude.agent

# claude.agent
base: ./reasoning-base.agent

# reasoning-base.agent
# (no base — root)
```

`resolve_inheritance` walks the chain bottom-up, merging at each level. Trust restricts at every step.

## Use cases

### Domain templates

```
bases/
  claude.agent              ← root for Claude
  claude-noether.agent      ← + Noether composition
ota/
  ota-base.agent            ← extends claude-noether, OTA-specific tools
  pricing-analyst.agent     ← extends ota-base, pricing focus
  recommendation-engine.agent ← extends ota-base, ML focus
```

A team builds the base once, all sub-agents inherit and customize.

### Sandboxing

```yaml
# enterprise-base.agent
trust:
  filesystem: scoped
  scope: [/workspace]
  network: scoped
  exec: sandboxed

# Any child agent published in the enterprise registry MUST extend this.
# They can restrict further (e.g., filesystem: none) but never escalate.
```

### Evolution (post-retro)

After a sprint retro, an agent evolves into a new version that extends the previous one:

```yaml
# caloron-agent-impl@1.1.0
base: caloron-agent-impl@1.0.0
merge:
  behavior: append   # add new traits learned from retro

behavior:
  traits:
    - self-review    # added because v1.0 had too many review cycles
    - handle-ambiguity
```

The full evolution chain is preserved, signed, and content-addressed.
