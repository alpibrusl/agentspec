# Sprint Integration

How [caloron-noether](https://github.com/alpibrusl/caloron-noether) uses AgentSpec for autonomous sprints.

## The flow

```
PO Agent generates DAG
      ↓
HR Agent + AgentSpec resolver  ← match tasks to agents (with profile context)
      ↓
Agents execute (claude-code, gemini-cli, codex-cli, ...)
      ↓
PRs merged, supervisor monitors
      ↓
Retro collects feedback per agent
      ↓
process_retro() → signed memories + portfolio entries
      ↓
Profiles persist to next sprint
```

## What gets stored per sprint

For each agent that ran a task, the sprint adds:

- **Memories**: blockers encountered, learnings from notes (signed)
- **Skill proofs**: each tool used → confidence boost (signed)
- **Portfolio entry**: project, sprint ID, tasks completed, tests passing (signed)
- **Evolution markers**: if the agent's `.agent` manifest evolved (signed)

## Code reference

```python
# In caloron-noether/orchestrator.py

from agentspec.profile.manager import ProfileManager
from agentspec.parser.manifest import AgentManifest

# After retro completes
profile_mgr = ProfileManager("./profiles")

for f in feedback_data:
    tid = f["task_id"]
    manifest = AgentManifest(
        name=f"caloron-agent-{tid}",
        version="1.0.0",
        description=task_data.get("title", ""),
    )
    profile = profile_mgr.load_or_create(manifest)

    result = profile_mgr.process_retro(
        profile, f,
        sprint_id=f"sprint-{sprint_number}",
        project=project_name,
    )

    print(f"  {tid}: {result['memories_added']} memories, "
          f"{result['skills_added']} skills, "
          f"{result['memories_signed']} signed")
```

## What the HR Agent does with profiles

Without profiles, HR Agent matches keywords:

```
task: "Implement pandas pipeline"
  → keywords: pandas, pipeline
  → assign: anyone with python skills
```

With profiles, HR Agent has history:

```
task: "Implement pandas pipeline"
  → check profiles for pandas skill demonstrated
  → agent A: pandas (95%, 12 sprints, completion rate 92%)
  → agent B: pandas (declared 30%, 0 sprints)
  → assign: agent A (proven track record)
```

## Sprint memories examples

After a real sprint completes:

| Memory | Category | Confidence |
|---|---|---|
| "pandas std=0 silently skips z-score" | `caloron:retro.blocker` | 0.9 |
| "Read-only filesystem in sandbox blocked pip install" | `caloron:retro.blocker` | 0.9 |
| "Rolling window 7 optimal for weekly hotel patterns" | `caloron:professional.domain_knowledge` | 0.6 |
| "Used pandas, fastapi, pytest, numpy" | (skill proofs) | 0.7 each |

All signed by the orchestrator's supervisor key.

## Cross-sprint learning

The killer use case. Sprint N's blockers become Sprint N+1's known knowledge:

**Sprint 1**: Agent fails because pandas std=0 in constant series → blocker recorded → memory signed.

**Sprint 2**: Same agent (or similar agent) starts. HR Agent reads profile, sees the memory. Includes it in the agent's system prompt:

```
Known issues to avoid:
- pandas std=0 silently skips z-score (from sprint-1 retro)
```

The agent doesn't repeat the mistake. Productivity compounds.

## Multi-team learning

Push the agent to your registry:

```bash
agentspec push caloron-agent-impl.agent --registry https://registry.mycompany.com
```

The full profile (with memories) ships. Another team pulls it:

```bash
agentspec pull caloron-agent-impl --registry https://registry.mycompany.com
```

They get an agent pre-loaded with your team's domain knowledge. Onboarding becomes free.

## Auditability

Every production decision is traceable:

```
Bug in production (anomaly detector misclassified rate spike)
  → which sprint produced this code? (PR commit message: [sprint-42])
  → which agent? (PR author: caloron-agent-impl)
  → load agent profile at sprint-42
  → check signed memories: "Window size 7 optimal for weekly patterns"
  → confidence 0.6 from sprint-7 — was this the wrong assumption?
```

The signed chain proves what the agent knew, when, and why it made the choice.

## Configuration

Set the profiles directory:

```python
# In caloron-noether/orchestrator.py
WORK = os.environ.get("WORK", "/tmp/caloron-full-loop")
profiles_dir = os.path.join(WORK, "profiles")
profile_mgr = ProfileManager(profiles_dir)
```

Persist across sprints by reusing the same `WORK` directory. Profiles accumulate forever until you delete them.
