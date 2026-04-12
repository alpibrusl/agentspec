# Profiles & Signing

Agent profiles are the killer feature. Every agent has a persistent identity that accumulates across sprints — a verifiable CV signed by the supervisor.

## What's in a profile

```python
class AgentProfile:
    agent_id: str             # tied to manifest.name
    agent_hash: str           # ag1:xxx — content hash of current manifest
    manifest_version: str     # current .agent version
    supervisor_pubkey: str    # for verifying signatures

    memories: list[Memory]            # signed learnings
    portfolio: list[PortfolioEntry]   # signed sprint results (the CV)
    skills: list[SkillProof]          # signed demonstrated capabilities
    signatures: list[SignedEnvelope]  # Ed25519 signatures
```

## Memories

Discrete units of accumulated knowledge:

```python
class Memory:
    id: str                        # mem_{content_hash}
    content: str                   # what the agent learned
    category: str                  # caloron:retro.blocker, etc.
    confidence: float              # 0.0–1.0
    status: MemoryStatus           # proposed | validated | archived | rejected
    source: MemorySource           # provenance (sprint, agent, evidence)
    tags: list[str]
    use_count: int                 # how often it's been useful
```

Categories follow the namespace convention `caloron:domain.subdomain`:

- `caloron:professional.domain_knowledge` — domain learnings
- `caloron:professional.tool_knowledge` — tool/library knowledge
- `caloron:preferences.coding_style` — style preferences
- `caloron:context.environment` — environment quirks
- `caloron:retro.blocker` — blockers from retros
- `caloron:retro.finding` — patterns identified
- `caloron:evolution.change` — evolution markers

## Portfolio entries

The CV: structured sprint results, signed by the supervisor.

```python
class PortfolioEntry:
    project: str
    sprint_id: str
    role: str
    tasks_completed: int
    tasks_total: int
    tests_passing: int
    avg_clarity: float
    review_cycles: float
    time_s: int
    technologies: list[str]
    pr_urls: list[str]
    completed_at: str
    signature: str    # Ed25519 over canonical bytes
```

## Skill proofs

Demonstrated capabilities with evidence and confidence:

```python
class SkillProof:
    skill: str             # "pandas", "fastapi", etc.
    level: str             # declared | demonstrated | proficient | expert
    evidence_type: str     # sprint | test_pass | code_review | benchmark
    evidence: str          # PR URL, test output, etc.
    sprint_id: str
    confidence: float
    signature: str
```

## Cold start

When you create a profile from a manifest with no prior history:

```python
from agentspec.profile import ProfileManager
from agentspec import load_agent

mgr = ProfileManager("./profiles")
manifest = load_agent("my-agent.agent")
profile = mgr.create_profile(manifest)
```

The profile is **seeded from the manifest**:

- Each declared skill becomes a `SkillProof` at confidence 0.3 (`level: declared`)
- A bootstrap memory captures persona + traits + capability tier
- A model preference memory for HR context
- Both bootstrap memories are signed at creation

This means the HR Agent always has context, even on the very first sprint.

## After a sprint

```python
mgr.process_retro(profile, feedback={
    "assessment": "completed",
    "clarity": 9,
    "blockers": [
        "pandas std=0 silently skips z-score",
        "Read-only filesystem blocked pip install",
    ],
    "tools": ["pandas", "fastapi", "pytest"],
    "notes": "Rolling z-score works well for hotel rate data",
    "time_s": 82,
    "tests_passing": 12,
}, sprint_id="sprint-1", project="OTA Anomaly Detector")
```

This produces:

- 2 memories from blockers (signed, confidence 0.9)
- 1 memory from notes (signed, confidence 0.6)
- 1 portfolio entry (signed)
- 3 skill proofs (pandas, fastapi, pytest at confidence 0.7)
- Skills upgraded from `declared` to `demonstrated`

All signed by the supervisor in one batch.

## Signing

Default: Ed25519 via PyNaCl. Falls back to HMAC-SHA256 if PyNaCl unavailable.

```python
from agentspec.profile import generate_keypair, sign_memory, verify_memory

private_key, public_key = generate_keypair()

# Supervisor signs
envelope = sign_memory(memory, private_key)

# Anyone verifies (with public key)
is_valid = verify_memory(memory, envelope)
```

Signed payload (canonical JSON, sorted keys):

```json
{
  "id": "mem_abc12345",
  "content": "pandas std=0 silently skips z-score",
  "category": "caloron:retro.blocker",
  "confidence": 0.9,
  "source": {
    "type": "agent_self_report",
    "agent_id": "caloron-agent-impl",
    "sprint_id": "sprint-1"
  },
  "created_at": "2026-04-12T10:30:00+00:00"
}
```

The signature commits to all of these. Tampering with any field invalidates the signature.

## Why this matters

Without signed profiles, you can't trust what an agent claims to know. With them:

- "This agent completed 12 sprints in OTA pricing" → cryptographically verifiable
- "This agent learned X" → traceable to a specific sprint with a specific supervisor
- Pull an agent from the registry → get its experience too, signed and authentic
- Audit any production decision back to the agent (and its training history)

## Publishing

Profiles ship alongside `.agent` manifests when pushed to a registry:

```bash
agentspec push my-agent.agent --registry https://registry.agentspec.dev
# Pushes manifest + profile (with signed portfolio)

agentspec pull <hash> --registry https://registry.agentspec.dev
# Pulls manifest + profile + signatures
```

Other teams can verify your supervisor's signatures against your published public key (`profiles/supervisor.pub`).

## See also

- [Cold Start guide](../guides/cold-start.md) — handling brand new agents
- [Sprint Integration](../guides/sprints.md) — how caloron-noether wires this in
