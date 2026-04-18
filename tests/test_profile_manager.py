"""Smoke tests for ProfileManager — create, save, load, sign memory, add entries."""

from __future__ import annotations

import pytest

from agentspec.parser.manifest import AgentManifest, BehaviorSpec, ModelSpec
from agentspec.profile.manager import ProfileManager
from agentspec.profile.models import PortfolioEntry, SkillProof
from agentspec.profile.signing import generate_keypair, public_key_for


@pytest.fixture
def manifest() -> AgentManifest:
    return AgentManifest(
        name="unit-test-agent",
        version="0.1.0",
        model=ModelSpec(capability="reasoning-mid"),
        behavior=BehaviorSpec(persona="careful test author", traits=["concise"]),
        skills=["python-development", "pytest-testing"],
    )


def test_create_profile_writes_supervisor_pub(tmp_path):
    pm = ProfileManager(str(tmp_path))
    profile = pm.create_profile(manifest_for("a"))

    assert profile.agent_id == "a"
    assert profile.supervisor_pubkey
    assert (tmp_path / "supervisor.pub").read_text() == pm.public_key


def test_supplied_private_key_yields_matching_pubkey(tmp_path):
    priv, pub = generate_keypair()
    pm = ProfileManager(str(tmp_path), supervisor_private_key=priv)

    assert pm.public_key == pub, (
        "ProfileManager must derive the real Ed25519 pubkey from the "
        "supplied private key, not sha256(private_key)"
    )
    assert pm.public_key == public_key_for(priv)


def test_generate_keypair_and_profile_manager_agree(tmp_path):
    """A profile created with no key (auto-gen) and one created with a
    supplied key must use matching pubkey formats; mixing must never
    happen because the earlier bug silently produced sha256-style pubkeys
    for supplied keys but verify-key-style pubkeys for generated ones."""
    pm_auto = ProfileManager(str(tmp_path / "auto"))
    priv_auto = pm_auto.private_key
    # Round-trip the same private key via a supplied init; must match.
    pm_supplied = ProfileManager(str(tmp_path / "supplied"), supervisor_private_key=priv_auto)
    assert pm_auto.public_key == pm_supplied.public_key


def test_profile_seeds_skill_proofs_from_manifest(manifest, tmp_path):
    pm = ProfileManager(str(tmp_path))
    profile = pm.create_profile(manifest)

    skills = [proof.skill for proof in profile.skills]
    assert "python-development" in skills
    assert "pytest-testing" in skills
    # Declared skills get confidence 0.3 by convention.
    for proof in profile.skills:
        if proof.level == "declared":
            assert proof.confidence == 0.3


def test_dict_form_skills_are_accepted(tmp_path):
    """v0.4.0 widened manifest.skills to accept dicts with a `name` key.
    ProfileManager must extract the name, not choke on the dict."""
    m = AgentManifest(
        name="b",
        version="0.1.0",
        skills=[{"name": "python-development", "requires": {"pip": ["pandas==2.0.0"]}}],
    )
    pm = ProfileManager(str(tmp_path))
    profile = pm.create_profile(m)

    skills = [proof.skill for proof in profile.skills]
    assert "python-development" in skills


def test_load_or_create_returns_existing_profile(manifest, tmp_path):
    pm = ProfileManager(str(tmp_path))
    first = pm.load_or_create(manifest)
    second = pm.load_or_create(manifest)

    # Same manifest + same profiles_dir → load, not re-create.
    assert first.agent_id == second.agent_id
    assert first.agent_hash == second.agent_hash


def test_add_sprint_result_signs_portfolio_entry(manifest, tmp_path):
    pm = ProfileManager(str(tmp_path))
    profile = pm.create_profile(manifest)

    added = pm.add_sprint_result(
        profile,
        project="unit-tests",
        sprint_id="s1",
        tasks_completed=3,
        tasks_total=3,
        tests_passing=3,
    )

    assert added.signature, "portfolio entry must be signed after add_sprint_result"
    assert len(added.signature) == 128, "Ed25519 signature is 64 bytes = 128 hex chars"


def test_add_skill_proof_signs_proof(manifest, tmp_path):
    pm = ProfileManager(str(tmp_path))
    profile = pm.create_profile(manifest)

    added = pm.add_skill_proof(
        profile,
        skill="python-development",
        evidence="all tests passing on sprint s1",
        sprint_id="s1",
    )

    assert added.signature
    assert len(added.signature) == 128


def manifest_for(name: str) -> AgentManifest:
    return AgentManifest(name=name, version="0.1.0")
