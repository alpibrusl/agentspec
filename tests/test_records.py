"""Tests for execution records (Proposal 001).

Covers the vertical slice of ExecutionRecord:

- ULID run-ID generation: 26-char Crockford base32, monotonic, unique
- ExecutionRecord Pydantic model: required vs optional fields
- RecordManager write → disk round-trip (unsigned plain JSON)
- Signed-envelope round-trip: sign on write, verify on read
- Tamper detection: modifying a byte in the record breaks verification
- Wrong-key rejection
- Listing / selecting records from a directory
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agentspec.records.manager import RecordManager, new_run_id
from agentspec.records.models import ExecutionRecord


def _minimal_record(run_id: str | None = None) -> ExecutionRecord:
    return ExecutionRecord(
        run_id=run_id or new_run_id(),
        manifest_hash="ag1:abc123def456",
        runtime="claude-code",
        started_at="2026-04-18T14:03:00Z",
        ended_at="2026-04-18T14:07:42Z",
        duration_s=282.13,
        exit_code=0,
        outcome="success",
    )


# ── ULID ──────────────────────────────────────────────────────────────────────


def test_new_run_id_is_26_chars():
    assert len(new_run_id()) == 26


def test_new_run_id_uses_crockford_base32_alphabet():
    # Crockford base32 excludes I, L, O, U to avoid ambiguity.
    id_ = new_run_id()
    forbidden = set("ILOU")
    assert not (set(id_) & forbidden), f"contains forbidden chars: {id_}"


def test_new_run_ids_are_unique():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50


def test_new_run_ids_are_monotonic():
    # Two IDs generated in order should sort in order (ULID guarantee).
    id1 = new_run_id()
    time.sleep(0.002)  # ensure different ms bucket
    id2 = new_run_id()
    assert id1 < id2


# ── Model validation ──────────────────────────────────────────────────────────


def test_execution_record_minimal_accepts_required_fields():
    r = _minimal_record()
    assert r.schema_ == "agentspec.record/v1"
    assert r.exit_code == 0
    assert r.outcome == "success"


def test_execution_record_rejects_unknown_outcome():
    with pytest.raises(Exception):  # pydantic ValidationError
        ExecutionRecord(
            run_id=new_run_id(),
            manifest_hash="ag1:abc",
            runtime="claude-code",
            started_at="2026-04-18T14:03:00Z",
            ended_at="2026-04-18T14:07:42Z",
            duration_s=10.0,
            exit_code=0,
            outcome="maybe",  # invalid
        )


def test_execution_record_optional_fields_default_none_or_empty():
    r = _minimal_record()
    assert r.lock_hash is None
    assert r.runtime_version is None
    assert r.model is None
    assert r.warnings == []
    assert r.token_usage is None
    assert r.tool_calls is None
    assert r.output_digest is None


# ── Unsigned write/read round-trip ────────────────────────────────────────────


def test_write_unsigned_creates_file_at_records_dir(tmp_path):
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    path = mgr.write(r)

    assert path.exists()
    assert path.parent == tmp_path / ".agentspec" / "records"
    assert path.name == f"{r.run_id}.json"


def test_unsigned_round_trip(tmp_path):
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    mgr.write(r)

    loaded = mgr.load(r.run_id)
    assert loaded == r


def test_unsigned_record_file_is_plain_json(tmp_path):
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    path = mgr.write(r)

    payload = json.loads(path.read_text())
    # Unsigned form: the record is the top-level object, no envelope wrapping.
    assert "signature" not in payload
    assert payload["run_id"] == r.run_id


# ── Signed write/read round-trip ──────────────────────────────────────────────


def test_write_signed_wraps_in_envelope(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    path = mgr.write(r, private_key=priv)

    envelope = json.loads(path.read_text())
    assert envelope["algorithm"] == "ed25519"
    assert envelope["public_key"] == pub
    assert len(envelope["signature"]) == 128  # Ed25519 sig = 64 bytes = 128 hex
    # Payload is nested under "payload".
    assert envelope["payload"]["run_id"] == r.run_id


def test_signed_round_trip(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    mgr.write(r, private_key=priv)

    loaded = mgr.load(r.run_id)
    # load() returns the ExecutionRecord regardless of envelope format.
    assert loaded == r


def test_verify_signed_record_with_correct_pubkey(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    mgr.write(r, private_key=priv)

    assert mgr.verify(r.run_id, pub) is True


def test_verify_rejects_wrong_pubkey(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    _, wrong_pub = generate_keypair()  # different pair
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    mgr.write(r, private_key=priv)

    assert mgr.verify(r.run_id, wrong_pub) is False


def test_verify_rejects_tampered_record(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    path = mgr.write(r, private_key=priv)

    # Mutate the on-disk record's exit_code; signature should no longer match.
    data = json.loads(path.read_text())
    data["payload"]["exit_code"] = 99
    path.write_text(json.dumps(data))

    assert mgr.verify(r.run_id, pub) is False


def test_verify_unsigned_returns_false(tmp_path):
    from agentspec.profile.signing import generate_keypair

    _, pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _minimal_record()
    mgr.write(r)  # no private_key → unsigned

    # Can't verify an unsigned record.
    assert mgr.verify(r.run_id, pub) is False


# ── Listing ───────────────────────────────────────────────────────────────────


def test_list_empty_directory_returns_empty(tmp_path):
    mgr = RecordManager(tmp_path)
    assert mgr.list() == []


def test_list_returns_records_newest_first(tmp_path):
    mgr = RecordManager(tmp_path)

    id1 = new_run_id()
    time.sleep(0.002)
    id2 = new_run_id()
    time.sleep(0.002)
    id3 = new_run_id()

    for rid in (id1, id2, id3):
        mgr.write(_minimal_record(run_id=rid))

    listed = mgr.list()
    assert [r.run_id for r in listed] == [id3, id2, id1]


def test_list_filters_by_manifest_hash(tmp_path):
    mgr = RecordManager(tmp_path)

    r1 = _minimal_record()
    r1.manifest_hash = "ag1:aaa"
    r2 = _minimal_record()
    r2.manifest_hash = "ag1:bbb"
    mgr.write(r1)
    mgr.write(r2)

    matches = mgr.list(manifest_hash="ag1:aaa")
    assert len(matches) == 1
    assert matches[0].manifest_hash == "ag1:aaa"


def test_load_missing_run_id_raises(tmp_path):
    mgr = RecordManager(tmp_path)
    with pytest.raises(FileNotFoundError):
        mgr.load("01JMISSING000000000000000X")
