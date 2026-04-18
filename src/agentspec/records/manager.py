"""Record writer + reader + verifier.

Records live at ``{base_dir}/.agentspec/records/<run-id>.json``. When a
signing key is supplied, the file wraps the record in an Ed25519 envelope
using the same canonical-JSON scheme as profile signing — so any audit
that covers ``agentspec.profile.signing`` covers records too.

The file format is one of:

- **Unsigned**: the record itself, serialised directly.
- **Signed envelope**::

    {
      "payload":    <record JSON, same shape as unsigned>,
      "algorithm":  "ed25519",
      "signature":  "<128-char hex>",
      "public_key": "<64-char hex>"
    }

``RecordManager.load`` is format-agnostic; ``verify`` requires a signed
envelope and returns False for unsigned files so callers cannot
accidentally "verify" something that was never signed.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from nacl.encoding import HexEncoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from agentspec.records.models import ExecutionRecord

ALGORITHM = "ed25519"

# Crockford base32: 0-9 A-Z minus I, L, O, U. Preserves ULID alphabet.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(data: bytes) -> str:
    """Encode exactly 16 bytes (128 bits) as 26 chars of Crockford base32.

    The first character holds only 3 bits (top of the 128-bit number),
    giving the standard ULID first-char range of 0-7.
    """
    if len(data) != 16:
        raise ValueError(f"expected 16 bytes, got {len(data)}")
    n = int.from_bytes(data, "big")
    return "".join(_CROCKFORD[(n >> (i * 5)) & 0x1F] for i in range(25, -1, -1))


def new_run_id() -> str:
    """Generate a ULID — 48-bit ms timestamp + 80-bit randomness.

    Sortable by creation time, globally unique under any reasonable
    entropy source, contains no PII. 26 chars, Crockford base32.
    """
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    payload = ts_ms.to_bytes(6, "big") + secrets.token_bytes(10)
    return _encode_crockford(payload)


def _canonical_payload(record: ExecutionRecord) -> bytes:
    """Canonical JSON of a record, for signing / verifying.

    Matches the profile-signing convention: ``sort_keys=True``, no
    explicit separators, aliases applied so "schema" (not "schema_")
    lands in the signed bytes.
    """
    payload = record.model_dump(exclude_none=True, by_alias=True)
    return json.dumps(payload, sort_keys=True).encode()


class RecordManager:
    """Manage execution records under a workspace directory.

    ``base_dir`` is the workspace root; records land in
    ``base_dir/.agentspec/records/``.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.records_dir = self.base_dir / ".agentspec" / "records"
        self.records_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.records_dir / f"{run_id}.json"

    def write(
        self,
        record: ExecutionRecord,
        *,
        private_key: str | None = None,
    ) -> Path:
        """Persist a record. When ``private_key`` is provided, wrap it in
        a signed Ed25519 envelope; otherwise write plain JSON."""
        path = self._path(record.run_id)
        if private_key:
            envelope = self._sign(record, private_key)
            path.write_text(json.dumps(envelope, indent=2))
        else:
            path.write_text(record.model_dump_json(indent=2, by_alias=True))
        return path

    def load(self, run_id: str) -> ExecutionRecord:
        """Load a record by ID. Transparent over signed vs unsigned files.

        Raises ``FileNotFoundError`` if the ID is unknown.
        """
        path = self._path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No record for run_id={run_id}")
        data = json.loads(path.read_text())
        return ExecutionRecord.model_validate(self._unwrap(data))

    def load_envelope(self, run_id: str) -> dict[str, Any]:
        """Load the raw on-disk JSON. Useful for inspecting signature metadata."""
        path = self._path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No record for run_id={run_id}")
        data: dict[str, Any] = json.loads(path.read_text())
        return data

    def verify(self, run_id: str, public_key_hex: str) -> bool:
        """Verify a signed record's Ed25519 signature.

        Returns False for any of: missing file, unsigned record, wrong
        algorithm, malformed hex, bad signature, or tampered payload.
        """
        path = self._path(run_id)
        if not path.exists():
            return False

        data = json.loads(path.read_text())
        if not self._is_envelope(data):
            return False
        if data.get("algorithm") != ALGORITHM:
            return False

        try:
            record = ExecutionRecord.model_validate(data["payload"])
        except Exception:
            return False

        canonical = _canonical_payload(record)
        try:
            vk = VerifyKey(bytes.fromhex(public_key_hex))
            vk.verify(canonical, bytes.fromhex(data["signature"]))
        except (BadSignatureError, ValueError):
            return False
        return True

    def list(
        self,
        *,
        manifest_hash: str | None = None,
    ) -> list[ExecutionRecord]:
        """List records, newest first (by ULID sort — no stat() calls).

        Filters: ``manifest_hash`` narrows to a specific agent.
        """
        results: list[ExecutionRecord] = []
        for path in self.records_dir.glob("*.json"):
            try:
                r = self.load(path.stem)
            except Exception as exc:
                log.warning("Skipping unreadable record %s: %s", path.name, exc)
                continue
            if manifest_hash is not None and r.manifest_hash != manifest_hash:
                continue
            results.append(r)
        results.sort(key=lambda r: r.run_id, reverse=True)
        return results

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_envelope(data: dict[str, Any]) -> bool:
        return "signature" in data and "payload" in data and "algorithm" in data

    @staticmethod
    def _unwrap(data: dict[str, Any]) -> dict[str, Any]:
        if RecordManager._is_envelope(data):
            payload = data["payload"]
            if isinstance(payload, dict):
                return payload
        return data

    def _sign(self, record: ExecutionRecord, private_key_hex: str) -> dict[str, Any]:
        canonical = _canonical_payload(record)
        sk = SigningKey(bytes.fromhex(private_key_hex))
        signed = sk.sign(canonical, encoder=HexEncoder)
        sig = signed.signature
        sig_hex = sig.decode() if isinstance(sig, bytes) else sig
        pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode()
        return {
            "payload": record.model_dump(exclude_none=True, by_alias=True),
            "algorithm": ALGORITHM,
            "signature": sig_hex,
            "public_key": pub_hex,
        }
