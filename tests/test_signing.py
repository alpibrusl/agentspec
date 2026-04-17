"""Tests for profile.signing — Ed25519 round-trip, tamper, wrong-key."""

from __future__ import annotations

import pytest

from agentspec.profile.models import (
    Memory,
    MemorySource,
    MemoryStatus,
    PortfolioEntry,
    SignedEnvelope,
    SkillProof,
)
from agentspec.profile.signing import (
    ALGORITHM,
    generate_keypair,
    public_key_for,
    sign_memory,
    sign_portfolio_entry,
    sign_skill_proof,
    verify_memory,
    verify_portfolio_entry,
    verify_skill_proof,
)


def _memory(content: str = "hello world", id_: str = "m1") -> Memory:
    return Memory(
        id=id_,
        content=content,
        status=MemoryStatus.VALIDATED,
        confidence=0.9,
        source=MemorySource(agent_id="unit-test", sprint_id="s1"),
    )


def _portfolio_entry() -> PortfolioEntry:
    return PortfolioEntry(
        project="p",
        sprint_id="s1",
        tasks_completed=3,
        tasks_total=5,
        tests_passing=5,
        completed_at="2026-04-17T00:00:00Z",
    )


def _skill_proof() -> SkillProof:
    return SkillProof(
        skill="python-development",
        level="demonstrated",
        evidence="tests passing on real sprint",
        sprint_id="s1",
        demonstrated_at="2026-04-17T00:00:00Z",
    )


# ── keypair + public-key derivation ───────────────────────────────────────────


def test_generate_keypair_produces_64_hex_chars_each():
    priv, pub = generate_keypair()
    assert len(priv) == 64 and len(pub) == 64
    int(priv, 16)  # valid hex
    int(pub, 16)


def test_public_key_for_matches_generate_keypair_output():
    """A passed-in private key must yield the same pubkey generate_keypair uses."""
    priv, pub = generate_keypair()
    assert public_key_for(priv) == pub


def test_public_key_for_is_deterministic():
    priv, pub = generate_keypair()
    assert public_key_for(priv) == public_key_for(priv) == pub


# ── memory round-trip, tamper, wrong-key ──────────────────────────────────────


def test_memory_round_trip():
    priv, _ = generate_keypair()
    m = _memory()
    env = sign_memory(m, priv)
    assert env.algorithm == ALGORITHM
    assert verify_memory(m, env) is True


def test_memory_rejects_tampered_content():
    priv, _ = generate_keypair()
    m = _memory(content="original")
    env = sign_memory(m, priv)

    tampered = _memory(content="tampered")
    assert verify_memory(tampered, env) is False


def test_memory_rejects_tampered_id():
    priv, _ = generate_keypair()
    m = _memory(id_="m1")
    env = sign_memory(m, priv)

    other = _memory(id_="m2")
    assert verify_memory(other, env) is False


def test_memory_rejects_wrong_signer_pubkey():
    priv_a, _ = generate_keypair()
    _, pub_b = generate_keypair()
    m = _memory()

    env = sign_memory(m, priv_a)
    forged = SignedEnvelope(
        memory_id=env.memory_id,
        signer=pub_b,  # someone else's key
        algorithm=env.algorithm,
        signature=env.signature,
    )
    assert verify_memory(m, forged) is False


def test_memory_rejects_malformed_signature():
    priv, _ = generate_keypair()
    m = _memory()
    env = sign_memory(m, priv)

    for bad_sig in ["", "xx", "nonhex" * 16, "0" * 63, "0" * 130]:
        bad_env = SignedEnvelope(
            memory_id=env.memory_id,
            signer=env.signer,
            algorithm=env.algorithm,
            signature=bad_sig,
        )
        assert verify_memory(m, bad_env) is False, f"should reject {bad_sig!r}"


def test_memory_rejects_unknown_algorithm():
    """The previous HMAC branch rubber-stamped any 64-char hex signature.
    Verify it no longer exists — envelopes with algorithm != 'ed25519' fail."""
    priv, _ = generate_keypair()
    m = _memory()
    env = sign_memory(m, priv)
    hmac_shaped = SignedEnvelope(
        memory_id=env.memory_id,
        signer=env.signer,
        algorithm="hmac-sha256",
        signature="a" * 64,
    )
    assert verify_memory(m, hmac_shaped) is False


# ── portfolio entry + skill proof round-trip + wrong-key ──────────────────────


def test_portfolio_entry_round_trip():
    priv, pub = generate_keypair()
    entry = _portfolio_entry()
    sig = sign_portfolio_entry(entry, priv)
    assert verify_portfolio_entry(entry, sig, pub) is True


def test_portfolio_entry_rejects_wrong_pubkey():
    priv, _ = generate_keypair()
    _, pub_b = generate_keypair()
    entry = _portfolio_entry()
    sig = sign_portfolio_entry(entry, priv)
    assert verify_portfolio_entry(entry, sig, pub_b) is False


def test_portfolio_entry_rejects_tampered_data():
    priv, pub = generate_keypair()
    entry = _portfolio_entry()
    sig = sign_portfolio_entry(entry, priv)

    tampered = _portfolio_entry()
    tampered.tasks_completed = entry.tasks_completed + 1
    assert verify_portfolio_entry(tampered, sig, pub) is False


def test_skill_proof_round_trip():
    priv, pub = generate_keypair()
    proof = _skill_proof()
    sig = sign_skill_proof(proof, priv)
    assert verify_skill_proof(proof, sig, pub) is True


def test_skill_proof_rejects_wrong_pubkey():
    priv, _ = generate_keypair()
    _, pub_b = generate_keypair()
    proof = _skill_proof()
    sig = sign_skill_proof(proof, priv)
    assert verify_skill_proof(proof, sig, pub_b) is False


# ── invalid private keys ──────────────────────────────────────────────────────


def test_sign_rejects_malformed_private_key():
    m = _memory()
    for bad in ["", "not hex", "0" * 63, "zz" * 32]:
        with pytest.raises((ValueError, TypeError)):
            sign_memory(m, bad)
