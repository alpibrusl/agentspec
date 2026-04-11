"""Pydantic models for agent profiles.

An agent profile contains:
- Identity: tied to AgentSpec manifest hash (ag1:xxx)
- Memories: categorized learnings from sprints (signed by supervisor)
- Portfolio: structured sprint results (the agent's CV)
- Skill proofs: demonstrated capabilities with evidence
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Memory ─────────────────────────────────────────────────────────────────


class MemoryCategory(str, Enum):
    """Standard memory categories. Extensible with ext:* prefix."""
    # Core categories
    DOMAIN_KNOWLEDGE = "caloron:professional.domain_knowledge"
    CODING_STYLE = "caloron:preferences.coding_style"
    TOOL_KNOWLEDGE = "caloron:professional.tool_knowledge"
    ENVIRONMENT = "caloron:context.environment"
    COMMUNICATION = "caloron:preferences.communication"
    # Retro-specific
    RETRO_FINDING = "caloron:retro.finding"
    RETRO_BLOCKER = "caloron:retro.blocker"
    RETRO_IMPROVEMENT = "caloron:retro.improvement"
    # Evolution
    EVOLUTION = "caloron:evolution.change"


class MemoryStatus(str, Enum):
    PROPOSED = "proposed"       # agent self-reported, not yet validated
    VALIDATED = "validated"     # supervisor confirmed and signed
    ARCHIVED = "archived"       # no longer active but kept for history
    REJECTED = "rejected"       # supervisor rejected the proposal


class MemorySource(BaseModel):
    """Where a memory came from — provenance chain."""
    type: str = "agent_self_report"  # agent_self_report | supervisor | retro | system
    agent_id: str = ""
    sprint_id: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence: Optional[str] = None   # PR URL, test output, etc.


class Memory(BaseModel):
    """A discrete unit of agent knowledge."""
    id: str = ""                     # mem_{hash[:8]}
    content: str                     # what the agent learned (max 2000 chars)
    category: str = MemoryCategory.DOMAIN_KNOWLEDGE.value
    confidence: float = 0.8          # 0.0-1.0, how reliable
    status: MemoryStatus = MemoryStatus.PROPOSED
    source: MemorySource = MemorySource()
    tags: list[str] = []
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    use_count: int = 0               # how many times this memory was useful


class SignedEnvelope(BaseModel):
    """Cryptographic envelope wrapping a signed memory."""
    memory_id: str
    signer: str                      # supervisor DID or public key
    algorithm: str = "ed25519"
    signature: str                   # hex-encoded Ed25519 signature
    signed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Portfolio ──────────────────────────────────────────────────────────────


class PortfolioEntry(BaseModel):
    """A completed sprint/project — the agent's CV entry."""
    project: str                     # project name/description
    sprint_id: str
    role: str = "developer"          # developer, reviewer, architect, etc.
    tasks_completed: int = 0
    tasks_total: int = 0
    tests_passing: int = 0
    avg_clarity: float = 0.0
    review_cycles: float = 0.0
    time_s: int = 0
    technologies: list[str] = []     # languages, frameworks used
    pr_urls: list[str] = []          # links to merged PRs
    completed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: Optional[str] = None  # supervisor signature over this entry


class SkillProof(BaseModel):
    """Demonstrated skill with evidence — verifiable capability."""
    skill: str                       # e.g. "python-pandas", "fastapi", "pytest"
    level: str = "demonstrated"      # demonstrated | proficient | expert
    evidence_type: str = "sprint"    # sprint | test_pass | code_review | benchmark
    evidence: str = ""               # PR URL, test output, benchmark result
    sprint_id: str = ""
    demonstrated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 0.8
    signature: Optional[str] = None


# ── Agent Profile ──────────────────────────────────────────────────────────


class AgentProfile(BaseModel):
    """Persistent agent identity — accumulates across sprints.

    Tied to an AgentSpec manifest via agent_hash.
    Published to noether-cloud registry alongside .agent files.
    """
    # Identity (tied to agentspec)
    agent_id: str                    # e.g. "caloron-agent-impl"
    agent_hash: str = ""             # ag1:xxx from agentspec manifest
    manifest_version: str = ""       # current .agent version

    # Profile metadata
    profile_version: str = "1.0.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Supervisor public key (for verifying signatures)
    supervisor_pubkey: str = ""

    # Accumulated knowledge
    memories: list[Memory] = []

    # Portfolio (CV)
    portfolio: list[PortfolioEntry] = []

    # Demonstrated skills
    skills: list[SkillProof] = []

    # Signed memory envelopes
    signatures: list[SignedEnvelope] = []

    def add_memory(self, memory: Memory) -> Memory:
        """Add a memory and assign it an ID."""
        import hashlib
        content_hash = hashlib.sha256(memory.content.encode()).hexdigest()[:8]
        memory.id = f"mem_{content_hash}"
        self.memories.append(memory)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return memory

    def validated_memories(self) -> list[Memory]:
        """Get only supervisor-validated memories."""
        return [m for m in self.memories if m.status == MemoryStatus.VALIDATED]

    def memories_by_category(self, category: str) -> list[Memory]:
        return [m for m in self.memories if m.category == category]

    def add_portfolio_entry(self, entry: PortfolioEntry) -> None:
        self.portfolio.append(entry)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_skill_proof(self, proof: SkillProof) -> None:
        # Update existing skill if confidence is higher
        for i, existing in enumerate(self.skills):
            if existing.skill == proof.skill and proof.confidence > existing.confidence:
                self.skills[i] = proof
                self.updated_at = datetime.now(timezone.utc).isoformat()
                return
        self.skills.append(proof)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def total_sprints(self) -> int:
        return len(self.portfolio)

    def completion_rate(self) -> float:
        if not self.portfolio:
            return 0.0
        total = sum(e.tasks_total for e in self.portfolio)
        completed = sum(e.tasks_completed for e in self.portfolio)
        return completed / total if total else 0.0

    def top_skills(self, n: int = 5) -> list[SkillProof]:
        return sorted(self.skills, key=lambda s: s.confidence, reverse=True)[:n]
