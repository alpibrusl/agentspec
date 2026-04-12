# API: Profile Manager

```python
from agentspec.profile import ProfileManager, AgentProfile, Memory, MemoryCategory
from agentspec import load_agent

mgr = ProfileManager("./profiles")
manifest = load_agent("my.agent")
profile = mgr.load_or_create(manifest)
```

## `ProfileManager`

```python
class ProfileManager:
    def __init__(
        self,
        profiles_dir: str,
        supervisor_private_key: str = "",   # auto-generates if empty
    ): ...

    def create_profile(self, manifest: AgentManifest) -> AgentProfile:
        """Cold start: seed from manifest (declared skills + bootstrap memories)."""

    def load_profile(self, agent_id: str) -> Optional[AgentProfile]: ...

    def load_or_create(self, manifest: AgentManifest) -> AgentProfile:
        """Load existing or create new."""

    def propose_memory(
        self, profile, content, category, confidence, sprint_id, evidence,
    ) -> Memory:
        """Agent self-reports a memory (status=proposed)."""

    def validate_memory(self, profile, memory_id) -> Optional[SignedEnvelope]:
        """Supervisor validates and signs."""

    def validate_all_proposed(self, profile) -> list[SignedEnvelope]:
        """Batch sign all proposed memories."""

    def add_sprint_result(
        self, profile, project, sprint_id, tasks_completed, tasks_total,
        tests_passing, avg_clarity, review_cycles, time_s,
        technologies, pr_urls,
    ) -> PortfolioEntry:
        """Add signed portfolio entry."""

    def add_skill_proof(
        self, profile, skill, evidence, sprint_id, level, confidence,
    ) -> SkillProof:
        """Add signed skill demonstration."""

    def process_retro(
        self, profile, feedback: dict, sprint_id, project,
    ) -> dict:
        """Convert sprint feedback into signed memories + portfolio + skills.

        feedback keys:
          - assessment: str
          - clarity: int
          - blockers: list[str]
          - tools: list[str]
          - notes: str
          - time_s: int
          - tests_passing: int (optional)
        """

    def export_profile(self, profile) -> str:
        """JSON for publishing to registry."""

    def print_profile_summary(self, profile) -> None: ...
```

## `AgentProfile`

```python
class AgentProfile(BaseModel):
    agent_id: str
    agent_hash: str            # ag1:xxx
    manifest_version: str
    profile_version: str = "1.0.0"
    created_at: str
    updated_at: str
    supervisor_pubkey: str

    memories: list[Memory]
    portfolio: list[PortfolioEntry]
    skills: list[SkillProof]
    signatures: list[SignedEnvelope]

    def add_memory(self, memory: Memory) -> Memory: ...
    def validated_memories(self) -> list[Memory]: ...
    def memories_by_category(self, category: str) -> list[Memory]: ...
    def add_portfolio_entry(self, entry: PortfolioEntry) -> None: ...
    def add_skill_proof(self, proof: SkillProof) -> None: ...
    def total_sprints(self) -> int: ...
    def completion_rate(self) -> float: ...
    def top_skills(self, n: int = 5) -> list[SkillProof]: ...
```

## `Memory`

```python
class Memory(BaseModel):
    id: str
    content: str
    category: str
    confidence: float = 0.8
    status: MemoryStatus = MemoryStatus.PROPOSED
    source: MemorySource
    tags: list[str]
    created_at: str
    use_count: int = 0
```

## `MemoryCategory`

```python
class MemoryCategory(str, Enum):
    DOMAIN_KNOWLEDGE = "caloron:professional.domain_knowledge"
    CODING_STYLE = "caloron:preferences.coding_style"
    TOOL_KNOWLEDGE = "caloron:professional.tool_knowledge"
    ENVIRONMENT = "caloron:context.environment"
    COMMUNICATION = "caloron:preferences.communication"
    RETRO_FINDING = "caloron:retro.finding"
    RETRO_BLOCKER = "caloron:retro.blocker"
    RETRO_IMPROVEMENT = "caloron:retro.improvement"
    EVOLUTION = "caloron:evolution.change"
```

Custom categories: use `ext:*` prefix.

## `PortfolioEntry`

```python
class PortfolioEntry(BaseModel):
    project: str
    sprint_id: str
    role: str = "developer"
    tasks_completed: int
    tasks_total: int
    tests_passing: int
    avg_clarity: float
    review_cycles: float
    time_s: int
    technologies: list[str]
    pr_urls: list[str]
    completed_at: str
    signature: Optional[str]
```

## `SkillProof`

```python
class SkillProof(BaseModel):
    skill: str
    level: str = "demonstrated"   # declared | demonstrated | proficient | expert
    evidence_type: str            # sprint | test_pass | code_review | benchmark
    evidence: str
    sprint_id: str
    demonstrated_at: str
    confidence: float = 0.8
    signature: Optional[str]
```

## Signing functions

```python
from agentspec.profile.signing import (
    generate_keypair,
    sign_memory,
    verify_memory,
    sign_portfolio_entry,
    sign_skill_proof,
)

private_key, public_key = generate_keypair()
envelope = sign_memory(memory, private_key)
is_valid = verify_memory(memory, envelope)
```

Uses Ed25519 via PyNaCl when available, falls back to HMAC-SHA256.
