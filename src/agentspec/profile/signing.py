"""Ed25519 signing for agent memories and portfolio entries.

The supervisor signs validated memories, making agent portfolios verifiable.
Anyone with the supervisor's public key can check that a memory, portfolio
entry, or skill proof was actually signed by the holder of the matching
private key.

PyNaCl is a hard dependency (declared in pyproject.toml). There is no
fallback: historical HMAC code masqueraded as signing while silently
rubber-stamping any signature-shaped string, so it has been removed
entirely. Run under a dev mode that explicitly refuses to produce
``SignedEnvelope`` if you need an unsigned flow.
"""

from __future__ import annotations

import json

from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from agentspec.profile.models import (
    Memory,
    PortfolioEntry,
    SignedEnvelope,
    SkillProof,
)

ALGORITHM = "ed25519"


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair. Returns ``(private_hex, public_hex)``."""
    sk = SigningKey.generate()
    private_hex = sk.encode(encoder=HexEncoder).decode()
    public_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
    return private_hex, public_hex


def public_key_for(private_key_hex: str) -> str:
    """Derive the Ed25519 public key (hex) from a private key (hex).

    This is the only correct way to recover a pubkey from a privkey.
    Previous ProfileManager code used ``sha256(private_key)`` which is
    a fingerprint of the secret, not a verifying key.
    """
    sk = SigningKey(bytes.fromhex(private_key_hex))
    return sk.verify_key.encode(encoder=HexEncoder).decode()


def _memory_payload(memory: Memory) -> bytes:
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


def _sign(payload: bytes, private_key_hex: str) -> tuple[str, str]:
    """Sign *payload* with the given private key. Returns ``(signature_hex, pubkey_hex)``."""
    sk = SigningKey(bytes.fromhex(private_key_hex))
    signed = sk.sign(payload, encoder=HexEncoder)
    signature = signed.signature
    sig_hex = signature.decode() if isinstance(signature, bytes) else signature
    pubkey_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
    return sig_hex, pubkey_hex


def sign_memory(memory: Memory, private_key: str) -> SignedEnvelope:
    """Sign a memory with the supervisor's private key."""
    sig_hex, pubkey_hex = _sign(_memory_payload(memory), private_key)
    return SignedEnvelope(
        memory_id=memory.id,
        signer=pubkey_hex,
        algorithm=ALGORITHM,
        signature=sig_hex,
    )


def verify_memory(memory: Memory, envelope: SignedEnvelope) -> bool:
    """Verify a signed memory against the envelope's declared public key.

    Returns ``False`` for any of: wrong algorithm, malformed hex, bad
    signature, mismatched payload.
    """
    if envelope.algorithm != ALGORITHM:
        return False

    try:
        vk = VerifyKey(bytes.fromhex(envelope.signer))
        vk.verify(_memory_payload(memory), bytes.fromhex(envelope.signature))
    except (BadSignatureError, ValueError):
        return False
    return True


def sign_portfolio_entry(entry: PortfolioEntry, private_key: str) -> str:
    """Sign a portfolio entry. Returns the hex signature."""
    sig_hex, _ = _sign(_portfolio_payload(entry), private_key)
    return sig_hex


def verify_portfolio_entry(
    entry: PortfolioEntry, signature_hex: str, public_key_hex: str
) -> bool:
    """Verify a portfolio entry signature against a known public key."""
    try:
        vk = VerifyKey(bytes.fromhex(public_key_hex))
        vk.verify(_portfolio_payload(entry), bytes.fromhex(signature_hex))
    except (BadSignatureError, ValueError):
        return False
    return True


def sign_skill_proof(proof: SkillProof, private_key: str) -> str:
    """Sign a skill proof. Returns the hex signature."""
    sig_hex, _ = _sign(_skill_payload(proof), private_key)
    return sig_hex


def verify_skill_proof(
    proof: SkillProof, signature_hex: str, public_key_hex: str
) -> bool:
    """Verify a skill proof signature against a known public key."""
    try:
        vk = VerifyKey(bytes.fromhex(public_key_hex))
        vk.verify(_skill_payload(proof), bytes.fromhex(signature_hex))
    except (BadSignatureError, ValueError):
        return False
    return True
