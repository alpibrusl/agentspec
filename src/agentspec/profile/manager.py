"""Profile manager — create, load, save, and update agent profiles.

Handles the lifecycle: create from agentspec manifest → accumulate
memories from sprints → sign with supervisor key → export/publish.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentspec.parser.loader import agent_hash, load_agent
from agentspec.parser.manifest import AgentManifest
from agentspec.profile.models import (
    AgentProfile,
    Memory,
    MemoryCategory,
    MemorySource,
    MemoryStatus,
    PortfolioEntry,
    SignedEnvelope,
    SkillProof,
)
from agentspec.profile.signing import (
    generate_keypair,
    public_key_for,
    sign_memory,
    sign_portfolio_entry,
    sign_skill_proof,
)


class ProfileManager:
    """Manages agent profiles — creation, updates, signing, persistence."""

    def __init__(self, profiles_dir: str, supervisor_private_key: str = ""):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Supervisor keypair for signing.
        # A passed-in private key must yield the same Ed25519 public key the
        # rest of the system expects; never substitute sha256(private_key),
        # which is a secret fingerprint, not a verifying key.
        if supervisor_private_key:
            self.private_key = supervisor_private_key
            self.public_key = public_key_for(supervisor_private_key)
        else:
            self.private_key, self.public_key = generate_keypair()

        # Save supervisor public key for verification
        pubkey_file = self.profiles_dir / "supervisor.pub"
        if not pubkey_file.exists():
            pubkey_file.write_text(self.public_key)

    def create_profile(self, manifest: AgentManifest) -> AgentProfile:
        """Create a new agent profile from an AgentSpec manifest.

        Cold start: seeds the profile with baseline skills and a bootstrap
        memory derived from the manifest. This ensures the HR Agent has
        context even on the very first sprint.
        """
        h = agent_hash(manifest)
        profile = AgentProfile(
            agent_id=manifest.name,
            agent_hash=h,
            manifest_version=manifest.version,
            supervisor_pubkey=self.public_key,
        )

        # ── Cold start: seed from manifest ─────────────────────────
        # Add declared skills as baseline proofs (low confidence — not yet demonstrated).
        # Skills may be plain strings or dicts (v0.4.0+); extract the name either way.
        for entry in manifest.skills:
            skill = entry if isinstance(entry, str) else entry.get("name", next(iter(entry)))
            profile.add_skill_proof(SkillProof(
                skill=skill,
                level="declared",
                evidence_type="manifest",
                evidence=f"Declared in .agent manifest v{manifest.version}",
                confidence=0.3,  # low — not yet demonstrated in a real sprint
            ))

        # Add a bootstrap memory with the agent's persona and traits
        traits = manifest.behavior.traits
        persona = manifest.behavior.persona
        if persona or traits:
            desc_parts = []
            if persona:
                desc_parts.append(f"Persona: {persona}")
            if traits:
                desc_parts.append(f"Traits: {', '.join(traits)}")
            if manifest.model.capability:
                desc_parts.append(f"Capability: {manifest.model.capability}")

            bootstrap = Memory(
                content=f"Agent initialized from manifest. {'. '.join(desc_parts)}.",
                category=MemoryCategory.EVOLUTION.value,
                confidence=1.0,
                status=MemoryStatus.VALIDATED,
                source=MemorySource(
                    type="system",
                    agent_id=manifest.name,
                    evidence=f"AgentSpec manifest {h}",
                ),
            )
            profile.add_memory(bootstrap)
            envelope = sign_memory(bootstrap, self.private_key)
            profile.signatures.append(envelope)

        # Add a bootstrap memory with model preference for HR context
        if manifest.model.preferred:
            model_mem = Memory(
                content=f"Preferred models: {', '.join(manifest.model.preferred[:3])}. "
                        f"Fallback: {manifest.model.fallback or 'none'}.",
                category=MemoryCategory.TOOL_KNOWLEDGE.value,
                confidence=1.0,
                status=MemoryStatus.VALIDATED,
                source=MemorySource(type="system", agent_id=manifest.name),
            )
            profile.add_memory(model_mem)
            envelope = sign_memory(model_mem, self.private_key)
            profile.signatures.append(envelope)

        self._save(profile)
        return profile

    def load_profile(self, agent_id: str) -> AgentProfile | None:
        """Load an existing profile."""
        path = self.profiles_dir / f"{agent_id}.profile.json"
        if not path.exists():
            return None
        return AgentProfile.model_validate_json(path.read_text())

    def load_or_create(self, manifest: AgentManifest) -> AgentProfile:
        """Load existing profile or create from manifest."""
        profile = self.load_profile(manifest.name)
        if profile:
            # Update manifest reference
            profile.agent_hash = agent_hash(manifest)
            profile.manifest_version = manifest.version
            return profile
        return self.create_profile(manifest)

    def _save(self, profile: AgentProfile) -> Path:
        path = self.profiles_dir / f"{profile.agent_id}.profile.json"
        path.write_text(profile.model_dump_json(indent=2))
        return path

    # ── Memory operations ──────────────────────────────────────────────

    def propose_memory(
        self,
        profile: AgentProfile,
        content: str,
        category: str = MemoryCategory.DOMAIN_KNOWLEDGE.value,
        confidence: float = 0.8,
        sprint_id: str = "",
        evidence: str = "",
    ) -> Memory:
        """Agent proposes a memory (status=proposed, not yet signed)."""
        memory = Memory(
            content=content,
            category=category,
            confidence=confidence,
            status=MemoryStatus.PROPOSED,
            source=MemorySource(
                type="agent_self_report",
                agent_id=profile.agent_id,
                sprint_id=sprint_id,
                evidence=evidence,
            ),
        )
        profile.add_memory(memory)
        self._save(profile)
        return memory

    def validate_memory(self, profile: AgentProfile, memory_id: str) -> SignedEnvelope | None:
        """Supervisor validates and signs a proposed memory."""
        for m in profile.memories:
            if m.id == memory_id and m.status == MemoryStatus.PROPOSED:
                m.status = MemoryStatus.VALIDATED
                envelope = sign_memory(m, self.private_key)
                profile.signatures.append(envelope)
                self._save(profile)
                return envelope
        return None

    def validate_all_proposed(self, profile: AgentProfile) -> list[SignedEnvelope]:
        """Validate and sign all proposed memories (batch operation)."""
        envelopes = []
        for m in profile.memories:
            if m.status == MemoryStatus.PROPOSED:
                m.status = MemoryStatus.VALIDATED
                envelope = sign_memory(m, self.private_key)
                profile.signatures.append(envelope)
                envelopes.append(envelope)
        if envelopes:
            self._save(profile)
        return envelopes

    # ── Portfolio operations ───────────────────────────────────────────

    def add_sprint_result(
        self,
        profile: AgentProfile,
        project: str,
        sprint_id: str,
        tasks_completed: int,
        tasks_total: int,
        tests_passing: int = 0,
        avg_clarity: float = 0.0,
        review_cycles: float = 0.0,
        time_s: int = 0,
        technologies: list[str] | None = None,
        pr_urls: list[str] | None = None,
    ) -> PortfolioEntry:
        """Add a sprint result to the agent's portfolio (signed by supervisor)."""
        entry = PortfolioEntry(
            project=project,
            sprint_id=sprint_id,
            tasks_completed=tasks_completed,
            tasks_total=tasks_total,
            tests_passing=tests_passing,
            avg_clarity=avg_clarity,
            review_cycles=review_cycles,
            time_s=time_s,
            technologies=technologies or [],
            pr_urls=pr_urls or [],
        )
        entry.signature = sign_portfolio_entry(entry, self.private_key)
        profile.add_portfolio_entry(entry)
        self._save(profile)
        return entry

    # ── Skill proofs ───────────────────────────────────────────────────

    def add_skill_proof(
        self,
        profile: AgentProfile,
        skill: str,
        evidence: str,
        sprint_id: str = "",
        level: str = "demonstrated",
        confidence: float = 0.8,
    ) -> SkillProof:
        """Add a demonstrated skill proof (signed by supervisor)."""
        proof = SkillProof(
            skill=skill,
            level=level,
            evidence=evidence,
            sprint_id=sprint_id,
            confidence=confidence,
        )
        proof.signature = sign_skill_proof(proof, self.private_key)
        profile.add_skill_proof(proof)
        self._save(profile)
        return proof

    # ── Retro integration ──────────────────────────────────────────────

    def process_retro(
        self,
        profile: AgentProfile,
        feedback: dict[str, Any],
        sprint_id: str,
        project: str = "",
    ) -> dict[str, Any]:
        """Process sprint retro data into profile memories + portfolio.

        Takes a feedback dict (from caloron-noether retro) and:
        1. Creates memories from blockers, findings, tools used
        2. Adds portfolio entry
        3. Adds skill proofs from tools used
        4. Validates and signs everything

        Returns summary of what was added.
        """
        added_memories = 0
        added_skills = 0

        # ── Memories from blockers ─────────────────────────────────
        for blocker in feedback.get("blockers", []):
            self.propose_memory(
                profile,
                content=blocker,
                category=MemoryCategory.RETRO_BLOCKER.value,
                confidence=0.9,
                sprint_id=sprint_id,
                evidence=f"Sprint {sprint_id} retro",
            )
            added_memories += 1

        # ── Memory from clarity ────────────────────────────────────
        clarity = feedback.get("clarity", 0)
        if clarity and clarity < 6:
            self.propose_memory(
                profile,
                content=f"Task clarity was {clarity}/10. Need more specific prompts with exact file paths and function signatures.",
                category=MemoryCategory.COMMUNICATION.value,
                confidence=0.7,
                sprint_id=sprint_id,
            )
            added_memories += 1

        # ── Memory from notes ──────────────────────────────────────
        notes = feedback.get("notes", "")
        if notes and len(notes) > 10:
            self.propose_memory(
                profile,
                content=notes[:2000],
                category=MemoryCategory.DOMAIN_KNOWLEDGE.value,
                confidence=0.6,
                sprint_id=sprint_id,
            )
            added_memories += 1

        # ── Skill proofs from tools used ───────────────────────────
        for tool in feedback.get("tools", []):
            self.add_skill_proof(
                profile,
                skill=tool,
                evidence=f"Used in sprint {sprint_id}",
                sprint_id=sprint_id,
                confidence=0.7,
            )
            added_skills += 1

        # ── Portfolio entry ────────────────────────────────────────
        completed = 1 if feedback.get("assessment") == "completed" else 0
        self.add_sprint_result(
            profile,
            project=project or f"sprint-{sprint_id}",
            sprint_id=sprint_id,
            tasks_completed=completed,
            tasks_total=1,
            tests_passing=feedback.get("tests_passing", 0),
            avg_clarity=clarity,
            review_cycles=len(feedback.get("blockers", [])),
            time_s=feedback.get("time_s", 0),
            technologies=feedback.get("tools", []),
        )

        # ── Validate and sign all proposed memories ────────────────
        envelopes = self.validate_all_proposed(profile)

        return {
            "memories_added": added_memories,
            "memories_signed": len(envelopes),
            "skills_added": added_skills,
            "portfolio_entries": 1,
            "total_memories": len(profile.memories),
            "total_portfolio": len(profile.portfolio),
            "total_skills": len(profile.skills),
        }

    # ── Export ─────────────────────────────────────────────────────────

    def export_profile(self, profile: AgentProfile) -> str:
        """Export profile as JSON (for publishing to registry)."""
        return profile.model_dump_json(indent=2)

    def print_profile_summary(self, profile: AgentProfile) -> None:
        """Print a human-readable profile summary."""
        print(f"  Agent: {profile.agent_id} ({profile.agent_hash})")
        print(f"  Manifest: v{profile.manifest_version}")
        print(f"  Sprints: {profile.total_sprints()}")
        print(f"  Completion rate: {profile.completion_rate():.0%}")
        print(f"  Memories: {len(profile.memories)} ({len(profile.validated_memories())} validated)")
        print(f"  Skills: {len(profile.skills)}")

        if profile.top_skills(3):
            top = ", ".join(f"{s.skill}({s.confidence:.0%})" for s in profile.top_skills(3))
            print(f"  Top skills: {top}")

        if profile.portfolio:
            last = profile.portfolio[-1]
            print(f"  Last sprint: {last.sprint_id} — {last.tasks_completed}/{last.tasks_total} tasks")
