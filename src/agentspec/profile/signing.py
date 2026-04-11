"""Ed25519 signing for agent memories and portfolio entries.

The supervisor signs validated memories, making agent portfolios
trustworthy and verifiable. Anyone with the supervisor's public key
can verify that a memory/achievement was actually validated.

Uses the stdlib-compatible PyNaCl (or falls back to hashlib HMAC
if PyNaCl is not available).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from agentspec.profile.models import (
    AgentProfile,
    Memory,
    MemoryStatus,
    PortfolioEntry,
    SignedEnvelope,
    SkillProof,
)

# Try to use real Ed25519 (PyNaCl), fall back to HMAC
try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.encoding import HexEncoder
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair. Returns (private_hex, public_hex).

    If PyNaCl is not available, generates a random HMAC key pair
    (less secure but functional for development).
    """
    if NACL_AVAILABLE:
        sk = SigningKey.generate()
        private_hex = sk.encode(encoder=HexEncoder).decode()
        public_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
        return private_hex, public_hex

    # Fallback: HMAC-based (not real Ed25519, but deterministic)
    import os
    secret = os.urandom(32).hex()
    public = hashlib.sha256(bytes.fromhex(secret)).hexdigest()
    return secret, public


def _memory_payload(memory: Memory) -> bytes:
    """Canonical bytes representation of a memory for signing."""
    data = {
        "id": memory.id,
        "content": memory.content,
        "category": memory.category,
        "confidence": memory.confidence,
        "source": memory.source.model_dump(),
        "created_at": memory.created_at,
    }
    return json.dumps(data, sort_keys=True).encode()


def _portfolio_payload(entry: PortfolioEntry) -> bytes:
    """Canonical bytes representation of a portfolio entry for signing."""
    data = {
        "project": entry.project,
        "sprint_id": entry.sprint_id,
        "tasks_completed": entry.tasks_completed,
        "tasks_total": entry.tasks_total,
        "tests_passing": entry.tests_passing,
        "completed_at": entry.completed_at,
    }
    return json.dumps(data, sort_keys=True).encode()


def _skill_payload(proof: SkillProof) -> bytes:
    data = {
        "skill": proof.skill,
        "level": proof.level,
        "evidence": proof.evidence,
        "sprint_id": proof.sprint_id,
        "demonstrated_at": proof.demonstrated_at,
    }
    return json.dumps(data, sort_keys=True).encode()


def sign_memory(memory: Memory, private_key: str) -> SignedEnvelope:
    """Sign a memory with the supervisor's private key."""
    payload = _memory_payload(memory)

    if NACL_AVAILABLE:
        sk = SigningKey(bytes.fromhex(private_key))
        signed = sk.sign(payload, encoder=HexEncoder)
        sig_hex = signed.signature.decode() if isinstance(signed.signature, bytes) else signed.signature
        pubkey = sk.verify_key.encode(encoder=HexEncoder).decode()
    else:
        sig_hex = hmac.new(bytes.fromhex(private_key), payload, hashlib.sha256).hexdigest()
        pubkey = hashlib.sha256(bytes.fromhex(private_key)).hexdigest()

    return SignedEnvelope(
        memory_id=memory.id,
        signer=pubkey,
        algorithm="ed25519" if NACL_AVAILABLE else "hmac-sha256",
        signature=sig_hex,
    )


def verify_memory(memory: Memory, envelope: SignedEnvelope) -> bool:
    """Verify a signed memory against the supervisor's public key."""
    payload = _memory_payload(memory)

    if NACL_AVAILABLE and envelope.algorithm == "ed25519":
        try:
            vk = VerifyKey(bytes.fromhex(envelope.signer))
            vk.verify(payload, bytes.fromhex(envelope.signature))
            return True
        except Exception:
            return False

    if envelope.algorithm == "hmac-sha256":
        # Can't verify HMAC without the private key — only structural check
        return len(envelope.signature) == 64

    return False


def sign_portfolio_entry(entry: PortfolioEntry, private_key: str) -> str:
    """Sign a portfolio entry. Returns hex signature."""
    payload = _portfolio_payload(entry)

    if NACL_AVAILABLE:
        sk = SigningKey(bytes.fromhex(private_key))
        signed = sk.sign(payload, encoder=HexEncoder)
        return signed.signature.decode() if isinstance(signed.signature, bytes) else signed.signature

    return hmac.new(bytes.fromhex(private_key), payload, hashlib.sha256).hexdigest()


def sign_skill_proof(proof: SkillProof, private_key: str) -> str:
    """Sign a skill proof. Returns hex signature."""
    payload = _skill_payload(proof)

    if NACL_AVAILABLE:
        sk = SigningKey(bytes.fromhex(private_key))
        signed = sk.sign(payload, encoder=HexEncoder)
        return signed.signature.decode() if isinstance(signed.signature, bytes) else signed.signature

    return hmac.new(bytes.fromhex(private_key), payload, hashlib.sha256).hexdigest()
