"""Tests for multi-tenant registry auth — AGENTSPEC_API_KEYS parsing,
per-tenant isolation on push/delete/get/list, and legacy singular-key
fallback mapping to the 'default' tenant.

Mirrors the model used by noether-cloud (tenant:key env format, isolated
storage per tenant, 404 cross-tenant on reads when authenticated).
"""

from __future__ import annotations

import os
import tempfile

# RegistryStorage resolves AGENTSPEC_REGISTRY_DIR at import time; seed
# one before importing so module-level construction does not fail.
os.environ.setdefault(
    "AGENTSPEC_REGISTRY_DIR",
    os.path.join(tempfile.gettempdir(), "agentspec-registry-mt-test"),
)

import pytest
from fastapi.testclient import TestClient

from agentspec.registry import server


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(server.API_KEY_ENV, raising=False)
    monkeypatch.delenv(server.API_KEYS_ENV, raising=False)
    monkeypatch.delenv(server.ALLOW_UNAUTH_ENV, raising=False)
    monkeypatch.setenv("AGENTSPEC_REGISTRY_DIR", str(tmp_path / "registry"))
    from agentspec.registry.storage import RegistryStorage

    server.storage = RegistryStorage()
    return monkeypatch


def _manifest(name: str = "example") -> dict:
    return {
        "name": name,
        "version": "0.1.0",
        "runtime": "claude-code",
    }


# ── _parse_keys unit tests ────────────────────────────────────────────────────


def test_parse_keys_basic():
    assert server._parse_keys("alice:k1,bob:k2") == {"k1": "alice", "k2": "bob"}


def test_parse_keys_strips_whitespace():
    assert server._parse_keys("  alice:k1 , bob:k2 ") == {"k1": "alice", "k2": "bob"}


def test_parse_keys_ignores_empty_entries():
    assert server._parse_keys("alice:k1,,bob:k2") == {"k1": "alice", "k2": "bob"}


def test_parse_keys_ignores_malformed():
    assert server._parse_keys("nocolon,alice:k1") == {"k1": "alice"}


def test_parse_keys_empty_string():
    assert server._parse_keys("") == {}


def test_parse_keys_colon_in_key_preserved():
    # Only splits on the first colon — key can contain colons.
    assert server._parse_keys("alice:some:key:with:colons") == {
        "some:key:with:colons": "alice"
    }


def test_parse_keys_rejects_path_traversal_tenant():
    # Tenant IDs become directory names; reject anything that could
    # escape the tenants root.
    assert server._parse_keys("../evil:key1") == {}
    assert server._parse_keys("alice/sub:key1") == {}
    assert server._parse_keys(".hidden:key1") == {}


def test_parse_keys_accepts_safe_tenant_chars():
    # Letters, digits, dash, underscore are allowed.
    assert server._parse_keys("alice-1:k1,bob_2:k2,TeamA:k3") == {
        "k1": "alice-1",
        "k2": "bob_2",
        "k3": "TeamA",
    }


# ── Legacy singular-key fallback → 'default' tenant ───────────────────────────


def test_legacy_single_key_maps_to_default_tenant(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "legacy-secret")
    client = TestClient(server.app)
    r = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "legacy-secret"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["tenant"] == server.DEFAULT_TENANT


def test_multi_keys_wins_over_legacy(clean_env):
    # When both AGENTSPEC_API_KEYS and AGENTSPEC_API_KEY are set, the
    # multi-tenant mapping takes precedence. Legacy key stops working.
    clean_env.setenv(server.API_KEY_ENV, "legacy-secret")
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key")

    client = TestClient(server.app)

    r1 = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "legacy-secret"},
    )
    assert r1.status_code == 401

    r2 = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "alice-key"},
    )
    assert r2.status_code == 201
    assert r2.json()["tenant"] == "alice"


# ── Multi-tenant push/delete isolation ────────────────────────────────────────


def test_multi_tenant_push_resolves_tenant_from_key(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    client = TestClient(server.app)

    r = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "alice-key"},
    )
    assert r.status_code == 201
    assert r.json()["tenant"] == "alice"


def test_multi_tenant_push_rejects_unknown_key(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key")
    client = TestClient(server.app)

    r = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert r.status_code == 401


def test_cross_tenant_delete_returns_404(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    client = TestClient(server.app)

    # Alice pushes.
    push = client.post(
        "/v1/agents",
        json=_manifest("alice-agent"),
        headers={"X-API-Key": "alice-key"},
    )
    assert push.status_code == 201
    ref = push.json()["hash"]

    # Bob cannot delete Alice's manifest — returns 404, not 401, because
    # from Bob's point of view the ref does not exist in his tenant.
    r = client.delete(f"/v1/agents/{ref}", headers={"X-API-Key": "bob-key"})
    assert r.status_code == 404

    # Alice can still delete her own.
    r2 = client.delete(f"/v1/agents/{ref}", headers={"X-API-Key": "alice-key"})
    assert r2.status_code == 200


def test_authenticated_pull_scoped_to_own_tenant(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    client = TestClient(server.app)

    push = client.post(
        "/v1/agents",
        json=_manifest("alice-agent"),
        headers={"X-API-Key": "alice-key"},
    )
    ref = push.json()["hash"]

    # Bob authenticates but cannot see Alice's manifest.
    r = client.get(f"/v1/agents/{ref}", headers={"X-API-Key": "bob-key"})
    assert r.status_code == 404

    # Alice can see her own.
    r2 = client.get(f"/v1/agents/{ref}", headers={"X-API-Key": "alice-key"})
    assert r2.status_code == 200


def test_authenticated_list_scoped_to_own_tenant(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    client = TestClient(server.app)

    client.post(
        "/v1/agents",
        json=_manifest("alice-agent"),
        headers={"X-API-Key": "alice-key"},
    )
    client.post(
        "/v1/agents",
        json=_manifest("bob-agent"),
        headers={"X-API-Key": "bob-key"},
    )

    alice_list = client.get("/v1/agents", headers={"X-API-Key": "alice-key"}).json()
    bob_list = client.get("/v1/agents", headers={"X-API-Key": "bob-key"}).json()

    alice_names = {a["name"] for a in alice_list["agents"]}
    bob_names = {a["name"] for a in bob_list["agents"]}

    assert alice_names == {"alice-agent"}
    assert bob_names == {"bob-agent"}


# ── Anonymous reads remain open (backwards compat) ────────────────────────────


def test_anonymous_list_sees_all_tenants(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    client = TestClient(server.app)

    client.post(
        "/v1/agents",
        json=_manifest("alice-agent"),
        headers={"X-API-Key": "alice-key"},
    )
    client.post(
        "/v1/agents",
        json=_manifest("bob-agent"),
        headers={"X-API-Key": "bob-key"},
    )

    r = client.get("/v1/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()["agents"]}
    assert names == {"alice-agent", "bob-agent"}


def test_anonymous_pull_by_ref_sees_any_tenant(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key")
    client = TestClient(server.app)

    push = client.post(
        "/v1/agents",
        json=_manifest("alice-agent"),
        headers={"X-API-Key": "alice-key"},
    )
    ref = push.json()["hash"]

    r = client.get(f"/v1/agents/{ref}")
    assert r.status_code == 200
    assert r.json()["manifest"]["name"] == "alice-agent"


def test_anonymous_write_still_rejected(clean_env):
    clean_env.setenv(server.API_KEYS_ENV, "alice:alice-key")
    client = TestClient(server.app)

    r = client.post("/v1/agents", json=_manifest())
    assert r.status_code == 401


# ── Storage tenant-scoping unit tests ─────────────────────────────────────────


def test_storage_isolates_by_tenant(tmp_path):
    from agentspec.parser.manifest import AgentManifest
    from agentspec.registry.storage import RegistryStorage

    storage = RegistryStorage(base_dir=str(tmp_path / "reg"))
    m = AgentManifest(name="example", version="0.1.0", runtime="claude-code")

    h = storage.save_agent(m, tenant="alice")

    # Alice sees it.
    assert storage.get_agent(h, tenant="alice") is not None
    # Bob does not.
    assert storage.get_agent(h, tenant="bob") is None
    # Anonymous (None) probes all tenants.
    assert storage.get_agent(h, tenant=None) is not None


def test_storage_delete_scoped_to_tenant(tmp_path):
    from agentspec.parser.manifest import AgentManifest
    from agentspec.registry.storage import RegistryStorage

    storage = RegistryStorage(base_dir=str(tmp_path / "reg"))
    m = AgentManifest(name="example", version="0.1.0", runtime="claude-code")

    h = storage.save_agent(m, tenant="alice")

    # Bob cannot delete Alice's.
    assert storage.delete_agent(h, tenant="bob") is False
    # Alice can.
    assert storage.delete_agent(h, tenant="alice") is True
    # Gone.
    assert storage.get_agent(h, tenant="alice") is None
