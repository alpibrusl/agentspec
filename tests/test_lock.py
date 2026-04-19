"""Tests for agentspec.lock — the 'pin the setup' half of proposal 001.

Covers:

- ``LockFile`` model validation (required + optional fields, schema alias)
- ``LockManager.create`` from a manifest + ResolvedPlan
- write/load round-trip for unsigned plain JSON
- write/load round-trip for Ed25519-signed envelope (same shape as records)
- ``verify`` against correct pubkey, tampered payload, wrong pubkey, unsigned
- ``plan_from_lock`` rehydrates a ResolvedPlan for ``agentspec run --lock``

No CLI or runner integration here — those are in test_cli_lock.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentspec.lock.manager import LockManager, plan_from_lock
from agentspec.lock.models import LockFile
from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.resolver import ResolvedPlan


def _manifest() -> AgentManifest:
    return AgentManifest(
        name="locktest",
        version="0.1.0",
        runtime="claude-code",
    )


def _plan(system_prompt: str = "you are a test agent.") -> ResolvedPlan:
    return ResolvedPlan(
        runtime="claude-code",
        model="claude/claude-sonnet-4-6",
        tools=["web-search", "cite-sources"],
        auth_source="env.ANTHROPIC_API_KEY",
        system_prompt=system_prompt,
        warnings=[],
        decisions=[],
    )


# ── LockFile model ────────────────────────────────────────────────────────────


def test_lockfile_schema_default():
    lf = LockManager.create(_manifest(), _plan())
    assert lf.schema_ == "agentspec.lock/v1"


def test_lockfile_populates_manifest_hash():
    m = _manifest()
    lf = LockManager.create(m, _plan())
    assert lf.manifest.hash == agent_hash(m)
    assert lf.manifest.name == "locktest"
    assert lf.manifest.version == "0.1.0"


def test_lockfile_populates_resolved_from_plan():
    p = _plan()
    lf = LockManager.create(_manifest(), p)
    assert lf.resolved.runtime == "claude-code"
    assert lf.resolved.model == "claude/claude-sonnet-4-6"
    assert set(lf.resolved.tools) == {"web-search", "cite-sources"}
    assert lf.resolved.auth_source == "env.ANTHROPIC_API_KEY"


def test_lockfile_hashes_system_prompt_but_does_not_store_text():
    prompt = "secret identity: be a helpful assistant for ACME corp"
    lf = LockManager.create(_manifest(), _plan(system_prompt=prompt))
    expected = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
    assert lf.resolved.system_prompt_hash == expected
    # Full prompt never in serialised lock (privacy).
    assert prompt not in lf.model_dump_json(by_alias=True, exclude_none=True)


def test_lockfile_populates_host_info():
    lf = LockManager.create(_manifest(), _plan())
    assert lf.host.os  # platform string
    assert lf.host.agentspec_version


def test_lockfile_has_generated_at_rfc3339():
    lf = LockManager.create(_manifest(), _plan())
    # RFC3339 with trailing Z.
    assert lf.generated_at.endswith("Z")
    assert "T" in lf.generated_at


# ── unsigned write / load round-trip ──────────────────────────────────────────


def test_write_unsigned_plain_json(tmp_path):
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path)

    data = json.loads(path.read_text())
    assert "signature" not in data
    assert data["manifest"]["name"] == "locktest"


def test_load_round_trip_unsigned(tmp_path):
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path)

    loaded = LockManager.load(path)
    assert loaded == lf


# ── signed envelope ───────────────────────────────────────────────────────────


def test_write_signed_wraps_in_envelope(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path, private_key=priv)

    envelope = json.loads(path.read_text())
    assert envelope["algorithm"] == "ed25519"
    assert envelope["public_key"] == pub
    assert len(envelope["signature"]) == 128
    assert envelope["payload"]["manifest"]["name"] == "locktest"


def test_signed_round_trip(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path, private_key=priv)

    loaded = LockManager.load(path)
    assert loaded == lf


def test_verify_with_correct_pubkey(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path, private_key=priv)

    assert LockManager.verify(path, pub) is True


def test_verify_rejects_wrong_pubkey(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    _, wrong_pub = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path, private_key=priv)

    assert LockManager.verify(path, wrong_pub) is False


def test_verify_rejects_tampered_payload(tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path, private_key=priv)

    data = json.loads(path.read_text())
    data["payload"]["resolved"]["model"] = "evil/model"
    path.write_text(json.dumps(data))

    assert LockManager.verify(path, pub) is False


def test_verify_rejects_unsigned_file(tmp_path):
    from agentspec.profile.signing import generate_keypair

    _, pub = generate_keypair()
    lf = LockManager.create(_manifest(), _plan())
    path = tmp_path / "a.lock"
    LockManager.write(lf, path)  # no signing

    assert LockManager.verify(path, pub) is False


def test_verify_missing_file_returns_false(tmp_path):
    from agentspec.profile.signing import generate_keypair

    _, pub = generate_keypair()
    assert LockManager.verify(tmp_path / "nope.lock", pub) is False


# ── plan_from_lock ────────────────────────────────────────────────────────────


def test_plan_from_lock_rehydrates_resolved_fields():
    lf = LockManager.create(_manifest(), _plan())
    plan = plan_from_lock(lf)
    assert plan.runtime == "claude-code"
    assert plan.model == "claude/claude-sonnet-4-6"
    assert set(plan.tools) == {"web-search", "cite-sources"}
    assert plan.auth_source == "env.ANTHROPIC_API_KEY"


def test_plan_from_lock_empties_system_prompt_to_avoid_drift():
    # The lock stores only a hash. The runner re-derives / the provisioner
    # writes instruction files from the manifest, so an empty prompt here
    # is correct — callers that need to hash-check re-derive themselves.
    prompt = "secret prompt"
    lf = LockManager.create(_manifest(), _plan(system_prompt=prompt))
    plan = plan_from_lock(lf)
    assert plan.system_prompt == ""


# ── PR #18 review regressions ─────────────────────────────────────────────────


def test_system_prompt_hash_rejects_none():
    """PR #18 review: hashing None silently produced the well-known
    sha256 of the empty string, which future drift-detection would
    falsely accept as 'matching'. None must raise."""
    from agentspec.lock.manager import _system_prompt_hash

    with pytest.raises((AttributeError, TypeError)):
        _system_prompt_hash(None)  # type: ignore[arg-type]


def test_lockfile_schema_excludes_schema_only_fields():
    """PR #18 review: ``runtime_version`` and ``mcp_servers`` were
    declared on LockedResolved but never populated — every emitted lock
    showed ``mcp_servers: []`` which a reader would misread as 'no MCP
    servers configured'. Until we can populate them meaningfully,
    they're dropped from the schema."""
    lf = LockManager.create(_manifest(), _plan())
    data = lf.model_dump(by_alias=True, exclude_none=True)
    resolved = data["resolved"]
    assert "runtime_version" not in resolved, (
        "runtime_version leaked as schema-only field — either populate "
        "from the plan or drop from the model"
    )
    assert "mcp_servers" not in resolved, (
        "mcp_servers leaked as schema-only field — either populate or drop"
    )
