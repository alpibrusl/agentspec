"""End-to-end push/pull round-trip against the agentspec-native
registry server.

Regression for the smoke-script failure: `pull_agent` didn't
recognise the native server's `{hash, manifest}` response shape.
It fell through to the Noether `/stages/{id}` fallback, which the
agentspec server doesn't serve, and returned None → CLI 404.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault(
    "AGENTSPEC_REGISTRY_DIR",
    os.path.join(tempfile.gettempdir(), "agentspec-roundtrip-test"),
)

import pytest
from fastapi.testclient import TestClient

from agentspec.parser.manifest import AgentManifest
from agentspec.registry import server
from agentspec.registry.client import pull_agent, push_agent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv(server.API_KEY_ENV, raising=False)
    monkeypatch.delenv(server.API_KEYS_ENV, raising=False)
    monkeypatch.delenv(server.ALLOW_UNAUTH_ENV, raising=False)
    monkeypatch.setenv("AGENTSPEC_REGISTRY_DIR", str(tmp_path / "registry"))
    monkeypatch.setenv(server.API_KEY_ENV, "test-key")

    from agentspec.registry.storage import RegistryStorage

    server.storage = RegistryStorage()
    return monkeypatch


@pytest.fixture
def live_server(monkeypatch, _clean_env):
    """Stand up the real FastAPI app via TestClient and patch the
    client's HTTP layer to speak to it. The client uses urllib, not
    httpx, so we monkeypatch ``_request`` to funnel through TestClient."""
    client = TestClient(server.app)

    def _fake_request(method, url, data=None):
        # Strip the scheme+host so TestClient can route by path alone.
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        headers = {}
        key = os.environ.get("AGENTSPEC_API_KEY")
        if key:
            headers["X-API-Key"] = key

        if method == "POST":
            r = client.post(path, json=data, headers=headers)
        elif method == "GET":
            r = client.get(path, headers=headers)
        elif method == "DELETE":
            r = client.delete(path, headers=headers)
        else:
            raise RuntimeError(f"unsupported method: {method}")

        # The real _request returns either the response JSON directly
        # (on 2xx) or an envelope with {"ok": False, "error": ...}
        # (on non-2xx). Mirror that exactly.
        if 200 <= r.status_code < 300:
            return r.json()
        try:
            body = r.json()
        except Exception:
            body = {}
        return body if body else {
            "ok": False,
            "error": {"code": str(r.status_code), "message": r.text},
        }

    import agentspec.registry.client as client_mod

    monkeypatch.setattr(client_mod, "_request", _fake_request)
    return "http://testclient"


def test_push_then_pull_authenticated_round_trip(live_server, monkeypatch):
    """Authenticated push + authenticated pull of the same manifest
    must yield back the pushed payload verbatim."""
    monkeypatch.setenv("AGENTSPEC_API_KEY", "test-key")

    original = AgentManifest(
        name="roundtrip-agent",
        version="0.2.0",
    )
    push_result = push_agent(original, live_server)
    assert "hash" in push_result, push_result
    ag_hash = push_result["hash"]

    pulled = pull_agent(ag_hash, live_server)
    assert pulled is not None, "pull returned None for a freshly-pushed hash"
    assert pulled.name == "roundtrip-agent"
    assert pulled.version == "0.2.0"


def test_pull_anonymous_succeeds_for_public_read(live_server, monkeypatch):
    """Anonymous pull (no X-API-Key) must succeed — the registry's
    read routes aggregate across tenants by design. This is the
    regression the smoke script surfaced: the client was silently
    failing to parse the server's native response shape."""
    # Push with auth; pull with none.
    monkeypatch.setenv("AGENTSPEC_API_KEY", "test-key")
    push_result = push_agent(
        AgentManifest(name="anon-readable", version="0.1.0", runtime="test-echo"),
        live_server,
    )
    ag_hash = push_result["hash"]

    monkeypatch.delenv("AGENTSPEC_API_KEY", raising=False)
    pulled = pull_agent(ag_hash, live_server)
    assert pulled is not None, \
        "anonymous pull returned None — public-read aggregation is broken"
    assert pulled.name == "anon-readable"


def test_pull_missing_hash_returns_none(live_server):
    """Pulling a hash that doesn't exist must return None (the CLI
    layer turns that into a NotFoundError)."""
    assert pull_agent("ag1:aaaaaaaaaaaaaaaa", live_server) is None


# ── Response-shape parsing: legacy / Noether compatibility ────────────────────


def test_pull_parses_noether_envelope_shape(monkeypatch):
    """PR #20 review asked for coverage of the Noether response shape —
    `{"ok": true, "data": {"result": {...manifest...}}}` — that the
    client's three-way parser still supports for downstream Noether
    registries. Mocks ``_request`` directly so we pin the wire contract
    without needing a Noether server stood up."""
    import agentspec.registry.client as client_mod

    def _fake_noether_request(method, url, data=None):
        assert method == "GET" and "/v1/agents/" in url
        return {
            "ok": True,
            "data": {
                "result": {
                    "name": "noether-shape-agent",
                    "version": "0.3.0",
                    "apiVersion": "agent/v1",
                },
            },
        }

    monkeypatch.setattr(client_mod, "_request", _fake_noether_request)
    pulled = pull_agent("ag1:deadbeef", "http://mock")
    assert pulled is not None
    assert pulled.name == "noether-shape-agent"
    assert pulled.version == "0.3.0"


def test_pull_parses_flat_manifest_shape(monkeypatch):
    """Last-resort fallback: some registries may return the manifest
    flat at the top level (no envelope, no nested ``manifest``/``result``
    key). The client detects this via the presence of ``name`` +
    ``version`` on the top-level dict and parses it directly."""
    import agentspec.registry.client as client_mod

    def _fake_flat_request(method, url, data=None):
        assert method == "GET" and "/v1/agents/" in url
        return {
            "name": "flat-shape-agent",
            "version": "0.4.0",
            "apiVersion": "agent/v1",
        }

    monkeypatch.setattr(client_mod, "_request", _fake_flat_request)
    pulled = pull_agent("ag1:deadbeef", "http://mock")
    assert pulled is not None
    assert pulled.name == "flat-shape-agent"
    assert pulled.version == "0.4.0"


# ── Multi-tenant public-read aggregation ──────────────────────────────────────


def test_pull_anonymous_aggregates_across_multiple_tenants(monkeypatch, tmp_path):
    """PR #20 review: the single-tenant anonymous-pull test proved
    "anonymous read works" but not the stronger claim that anonymous
    reads **aggregate across tenants**. Set up a real multi-tenant
    server, have alice and bob each push an agent, then pull both
    anonymously from a third tenant-less context."""
    monkeypatch.delenv(server.API_KEY_ENV, raising=False)
    monkeypatch.setenv(server.API_KEYS_ENV, "alice:alice-key,bob:bob-key")
    monkeypatch.setenv("AGENTSPEC_REGISTRY_DIR", str(tmp_path / "multi-tenant-registry"))

    from agentspec.registry.storage import RegistryStorage

    server.storage = RegistryStorage()
    client = TestClient(server.app)

    def _req(method, url, data=None, api_key=None):
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        headers = {"X-API-Key": api_key} if api_key else {}
        if method == "POST":
            r = client.post(path, json=data, headers=headers)
        else:
            r = client.get(path, headers=headers)
        if 200 <= r.status_code < 300:
            return r.json()
        return {"ok": False, "error": {"code": str(r.status_code), "message": r.text}}

    import agentspec.registry.client as client_mod

    # Alice pushes her agent.
    monkeypatch.setattr(
        client_mod, "_request", lambda m, u, data=None: _req(m, u, data, "alice-key")
    )
    alice_hash = push_agent(
        AgentManifest(name="alice-agent", version="0.1.0"), "http://mock"
    )["hash"]

    # Bob pushes a different agent under his tenant.
    monkeypatch.setattr(
        client_mod, "_request", lambda m, u, data=None: _req(m, u, data, "bob-key")
    )
    bob_hash = push_agent(
        AgentManifest(name="bob-agent", version="0.1.0"), "http://mock"
    )["hash"]

    # Anonymous pulls (no API key) must see BOTH tenants' agents.
    monkeypatch.setattr(
        client_mod, "_request", lambda m, u, data=None: _req(m, u, data, None)
    )
    alice_pulled = pull_agent(alice_hash, "http://mock")
    bob_pulled = pull_agent(bob_hash, "http://mock")

    assert alice_pulled is not None, "anonymous pull of alice's agent failed"
    assert alice_pulled.name == "alice-agent"
    assert bob_pulled is not None, "anonymous pull of bob's agent failed"
    assert bob_pulled.name == "bob-agent"
