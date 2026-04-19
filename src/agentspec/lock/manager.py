"""Write / load / verify agentspec.lock files.

Signing reuses the Ed25519 envelope shape from records and signed
profile memories: ``{payload, algorithm, signature, public_key}`` with
``algorithm == "ed25519"`` and canonical JSON (``sort_keys=True``) for
both signing and verification. Sharing the shape keeps the audit story
consistent: any tool that knows how to verify a signed memory can
verify a signed lock.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from agentspec.lock.models import LockedHost, LockedManifest, LockedResolved, LockFile
from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.resolver import ResolvedPlan

ALGORITHM = "ed25519"


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _host_string() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return f"{system}-{machine}" if machine else system


def _agentspec_version() -> str:
    try:
        return _pkg_version("agentspec-alpibru")
    except PackageNotFoundError:
        return "unknown"


def _system_prompt_hash(prompt: str | None) -> str:
    return "sha256:" + hashlib.sha256((prompt or "").encode()).hexdigest()


def _canonical(lock: LockFile) -> bytes:
    payload = lock.model_dump(exclude_none=True, by_alias=True)
    return json.dumps(payload, sort_keys=True).encode()


class LockManager:
    """Build, persist, and verify ``agentspec.lock`` documents."""

    @staticmethod
    def create(manifest: AgentManifest, plan: ResolvedPlan) -> LockFile:
        """Build a ``LockFile`` from a manifest + resolved plan.

        The lock pins the resolver's output, not the manifest's source
        YAML — a hash of the manifest is enough to detect drift when
        the lock is later used to run the agent.
        """
        return LockFile(
            manifest=LockedManifest(
                hash=agent_hash(manifest),
                name=manifest.name,
                version=manifest.version,
            ),
            resolved=LockedResolved(
                runtime=plan.runtime,
                model=plan.model or "",
                tools=list(plan.tools or []),
                auth_source=plan.auth_source,
                system_prompt_hash=_system_prompt_hash(plan.system_prompt),
            ),
            host=LockedHost(
                os=_host_string(),
                agentspec_version=_agentspec_version(),
            ),
            generated_at=_utc_now_iso(),
            warnings=list(plan.warnings or []),
        )

    @staticmethod
    def write(
        lock: LockFile,
        path: str | Path,
        *,
        private_key: str | None = None,
    ) -> Path:
        """Persist a lock. When ``private_key`` is set, wrap in an
        Ed25519 envelope using the same shape as signed records."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if private_key:
            envelope = _sign(lock, private_key)
            p.write_text(json.dumps(envelope, indent=2))
        else:
            p.write_text(lock.model_dump_json(indent=2, by_alias=True, exclude_none=True))
        return p

    @staticmethod
    def load(path: str | Path) -> LockFile:
        """Load a lock — transparent over signed and unsigned formats."""
        data = json.loads(Path(path).read_text())
        if _is_envelope(data):
            return LockFile.model_validate(data["payload"])
        return LockFile.model_validate(data)

    @staticmethod
    def verify(path: str | Path, public_key_hex: str) -> bool:
        """Ed25519-verify a signed lock. False for missing files,
        unsigned locks, mismatched algorithm, bad signatures, or
        tampered payloads."""
        p = Path(path)
        if not p.exists():
            return False
        data = json.loads(p.read_text())
        if not _is_envelope(data) or data.get("algorithm") != ALGORITHM:
            return False
        try:
            lock = LockFile.model_validate(data["payload"])
        except Exception:
            return False
        canonical = _canonical(lock)
        try:
            vk = VerifyKey(bytes.fromhex(public_key_hex))
            vk.verify(canonical, bytes.fromhex(data["signature"]))
        except (BadSignatureError, ValueError):
            return False
        return True


def plan_from_lock(lock: LockFile) -> ResolvedPlan:
    """Rehydrate a ResolvedPlan from a lock for ``agentspec run --lock``.

    ``system_prompt`` is intentionally empty — the lock stores only a
    hash, and the provisioner writes the real instruction content into
    native CLI config files (CLAUDE.md, GEMINI.md, …) from the manifest
    anyway, so downstream runners that read those don't care. Callers
    that need prompt-drift detection re-hash the resolver's current
    output and compare it with ``lock.resolved.system_prompt_hash``.
    """
    return ResolvedPlan(
        runtime=lock.resolved.runtime,
        model=lock.resolved.model,
        tools=list(lock.resolved.tools),
        auth_source=lock.resolved.auth_source,
        system_prompt="",
        warnings=list(lock.warnings),
        decisions=[f"loaded from lock (agentspec {lock.host.agentspec_version})"],
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_envelope(data: dict[str, Any]) -> bool:
    return "signature" in data and "payload" in data and "algorithm" in data


def _sign(lock: LockFile, private_key_hex: str) -> dict[str, Any]:
    canonical = _canonical(lock)
    sk = SigningKey(bytes.fromhex(private_key_hex))
    signed = sk.sign(canonical, encoder=HexEncoder)
    sig = signed.signature
    sig_hex = sig.decode() if isinstance(sig, bytes) else sig
    pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
    return {
        "payload": lock.model_dump(exclude_none=True, by_alias=True),
        "algorithm": ALGORITHM,
        "signature": sig_hex,
        "public_key": pub_hex,
    }
