"""Tests for registry server auth — X-API-Key enforcement on mutating routes."""

from __future__ import annotations

import os
import tempfile

# Registry storage resolves AGENTSPEC_REGISTRY_DIR at import time; set a
# writable default before importing so module-level storage construction
# does not fail on systems without /data.
os.environ.setdefault(
    "AGENTSPEC_REGISTRY_DIR",
    os.path.join(tempfile.gettempdir(), "agentspec-registry-test"),
)

import pytest
from fastapi.testclient import TestClient

from agentspec.registry import server


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(server.API_KEY_ENV, raising=False)
    monkeypatch.delenv(server.ALLOW_UNAUTH_ENV, raising=False)
    monkeypatch.setenv("AGENTSPEC_REGISTRY_DIR", str(tmp_path / "registry"))
    # Reset the registry's storage to point at the fresh dir.
    from agentspec.registry.storage import RegistryStorage

    server.storage = RegistryStorage()
    return monkeypatch


def _manifest() -> dict:
    return {
        "name": "example",
        "version": "0.1.0",
        "runtime": "claude-code",
    }


def test_push_rejects_missing_key(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    r = client.post("/v1/agents", json=_manifest())
    assert r.status_code == 401
    assert "X-API-Key" in r.json()["detail"]


def test_push_rejects_wrong_key(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    r = client.post("/v1/agents", json=_manifest(), headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_push_accepts_correct_key(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    r = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "server-secret"},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "example"


def test_push_returns_503_when_server_key_unset(clean_env):
    client = TestClient(server.app)
    r = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "anything"},
    )
    assert r.status_code == 503


def test_allow_unauthenticated_opt_in(clean_env):
    clean_env.setenv(server.ALLOW_UNAUTH_ENV, "1")
    client = TestClient(server.app)
    r = client.post("/v1/agents", json=_manifest())
    assert r.status_code == 201


def test_delete_requires_auth(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    # Push with valid auth first.
    client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "server-secret"},
    )
    # Delete without auth → 401.
    r = client.delete("/v1/agents/example:0.1.0")
    assert r.status_code == 401


def test_read_routes_stay_public(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/agents").status_code == 200


def test_delete_accepts_correct_key(clean_env):
    clean_env.setenv(server.API_KEY_ENV, "server-secret")
    client = TestClient(server.app)
    push = client.post(
        "/v1/agents",
        json=_manifest(),
        headers={"X-API-Key": "server-secret"},
    )
    ref = push.json()["hash"]
    r = client.delete(f"/v1/agents/{ref}", headers={"X-API-Key": "server-secret"})
    assert r.status_code == 200
