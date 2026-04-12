# Cold Start

What happens when an agent has no history? AgentSpec gracefully handles brand new agents through manifest seeding.

## The problem

A fresh `.agent` manifest has:

- Declared skills (but no demonstrated proficiency)
- Persona and traits (but no track record)
- Model preferences (but no proven cost/quality data)

If the HR Agent (in caloron-noether) reads this profile, what does it see? Nothing useful — yet.

## The solution: seed from manifest

`ProfileManager.create_profile()` seeds the profile from the manifest itself:

```python
mgr = ProfileManager("./profiles")
manifest = load_agent("brand-new.agent")
profile = mgr.create_profile(manifest)
```

The new profile contains:

### 1. Declared skills (low confidence)

Each `manifest.skills` entry becomes a `SkillProof`:

```python
SkillProof(
    skill="web-search",
    level="declared",          # not yet demonstrated
    evidence_type="manifest",
    evidence="Declared in .agent manifest v1.0.0",
    confidence=0.3,            # low — not yet proven in real sprints
)
```

### 2. Bootstrap memory (signed)

A signed memory captures the agent's identity:

```
content: "Agent initialized from manifest. Persona: precise-researcher.
          Traits: cite-everything, never-guess. Capability: reasoning-high."
category: caloron:evolution.change
status: validated
confidence: 1.0
```

### 3. Model preference memory (signed)

For HR Agent context:

```
content: "Preferred models: claude/claude-sonnet-4-6, gemini/gemini-2.5-pro,
          local/llama3:70b. Fallback: reasoning-mid."
category: caloron:professional.tool_knowledge
status: validated
confidence: 1.0
```

## After the first sprint

When skills get used in a real sprint:

```python
mgr.process_retro(profile, feedback={
    "tools": ["web-search", "cite-sources"],   # actually used
    "assessment": "completed",
}, sprint_id="sprint-1")
```

The matching skill proofs **upgrade**:

```
Before:  web-search: declared (30%)
After:   web-search: demonstrated (70%)
```

Skills not used stay at `declared (30%)` until their first real sprint.

## What the HR Agent sees

Cold start (sprint 1):

```
Agent: deep-researcher
  Sprints: 0
  Skills (3, all declared at 30%):
    web-search, cite-sources, summarize
  Memories: 2 (bootstrap, model preferences)
  Portfolio: empty
```

After sprint 1:

```
Agent: deep-researcher
  Sprints: 1
  Skills (3, 2 demonstrated):
    web-search: demonstrated (70%)
    cite-sources: demonstrated (70%)
    summarize: declared (30%)        # not used yet
  Memories: 4 (bootstrap + 2 retro findings + 1 note)
  Portfolio: 1 entry — Quantum Research, 1/1 tasks
  Completion rate: 100%
```

After 10 sprints:

```
Agent: deep-researcher
  Sprints: 10
  Skills (8, 6 expert):
    web-search: expert (95%)
    cite-sources: expert (92%)
    arxiv-mcp: proficient (85%)
    ...
  Memories: 47 (validated, signed)
  Portfolio: 10 entries across 4 projects
  Completion rate: 90%
```

## Why this matters

The cold start design ensures:

1. **The HR Agent always has something to work with** — even on day 1, it knows what skills the agent declares and what runtime to use
2. **No special-case code** — the same `process_retro()` flow works for sprint 1 and sprint 100
3. **Honest signaling** — `declared(30%)` vs `demonstrated(70%)` makes confidence visible
4. **Fast bootstrap** — agents become useful immediately, not after some warmup period

## Resetting an agent

To reset an agent's profile (start over):

```python
import shutil
shutil.rmtree("./profiles")  # nuclear option

# Or per-agent
import os
os.remove(f"./profiles/{agent_id}.profile.json")

# Recreate
profile = mgr.create_profile(manifest)
```

The `agent_hash` in the profile ties it to a specific manifest version. If the manifest changes, you can keep the old profile or start fresh.
