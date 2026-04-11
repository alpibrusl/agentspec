"""Agent profiles — persistent identity, memories, and portfolio for AI agents.

Agents accumulate memories from sprint retros, building a portfolio (CV)
of demonstrated skills. Memories are signed by the supervisor for authenticity.
"""

from agentspec.profile.models import (
    AgentProfile,
    Memory,
    MemoryCategory,
    MemorySource,
    MemoryStatus,
    PortfolioEntry,
    SkillProof,
    SignedEnvelope,
)
from agentspec.profile.signing import generate_keypair, sign_memory, verify_memory
from agentspec.profile.manager import ProfileManager

__all__ = [
    "AgentProfile",
    "Memory",
    "MemoryCategory",
    "MemorySource",
    "MemoryStatus",
    "PortfolioEntry",
    "ProfileManager",
    "SignedEnvelope",
    "SkillProof",
    "generate_keypair",
    "sign_memory",
    "verify_memory",
]
