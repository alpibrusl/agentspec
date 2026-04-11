"""HTTP client for talking to Noether-cloud registry.

Wraps .agent manifests as Noether stage specs for storage in the registry.
Uses the same POST /stages and GET /stages endpoints.

The trick: an .agent manifest is stored as a Noether stage where:
- name = "agent:{manifest.name}"
- description = manifest.description
- implementation = manifest JSON (the full .agent content)
- tags = ["agentspec", "agent-manifest"] + manifest.tags
- input/output types = Record{} → Record{} (metadata-only stage)
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from agentspec.parser.manifest import AgentManifest
from agentspec.parser.loader import agent_hash


def _registry_url() -> str:
    """Get the registry URL from env or raise."""
    url = os.environ.get("AGENTSPEC_REGISTRY") or os.environ.get("NOETHER_REGISTRY", "")
    return url.rstrip("/")


def _api_key() -> str:
    return os.environ.get("AGENTSPEC_API_KEY") or os.environ.get("NOETHER_API_KEY", "")


def _manifest_to_stage_spec(manifest: AgentManifest) -> dict[str, Any]:
    """Wrap an AgentManifest as a Noether stage spec for registry storage."""
    manifest_json = manifest.model_dump(exclude_none=True)
    # Remove internal fields
    manifest_json.pop("_source_dir", None)

    return {
        "name": f"agent:{manifest.name}",
        "description": manifest.description or f"Agent: {manifest.name}",
        "input": {"Record": []},
        "output": {"Record": [["manifest", "Any"]]},
        "effects": [],
        "language": "python",
        "implementation": json.dumps(manifest_json),
        "examples": [
            {
                "input": {},
                "output": {"manifest": {"name": manifest.name, "version": manifest.version}},
            }
        ],
        "tags": ["agentspec", "agent-manifest"] + manifest.tags[:5],
    }


def _stage_to_manifest(stage_data: dict[str, Any]) -> AgentManifest | None:
    """Extract an AgentManifest from a Noether stage's implementation field."""
    impl = stage_data.get("implementation", "")
    if not impl:
        return None
    try:
        manifest_dict = json.loads(impl)
        return AgentManifest(**manifest_dict)
    except (json.JSONDecodeError, Exception):
        return None


def _request(
    method: str, url: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make an HTTP request to the registry."""
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["X-API-Key"] = key

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            return json.loads(body_text)
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": str(e.code), "message": body_text}}
    except urllib.error.URLError as e:
        return {"ok": False, "error": {"code": "CONNECTION_ERROR", "message": str(e.reason)}}


def push_agent(manifest: AgentManifest, registry_url: str = "") -> dict[str, Any]:
    """Push an .agent manifest to the Noether registry.

    Returns: {"hash": "ag1:xxx", "registry_id": "abc...", "name": ..., "version": ...}
    """
    url = registry_url or _registry_url()
    if not url:
        raise ValueError(
            "No registry URL. Set AGENTSPEC_REGISTRY or NOETHER_REGISTRY env var, "
            "or pass --registry URL"
        )

    spec = _manifest_to_stage_spec(manifest)
    result = _request("POST", f"{url}/stages", spec)

    h = agent_hash(manifest)
    if result.get("ok") is not False:
        # Extract the registry stage ID
        stage_id = ""
        if isinstance(result, dict):
            data = result.get("data", result)
            stage_id = data.get("id", "")

        return {
            "hash": h,
            "registry_id": stage_id,
            "name": manifest.name,
            "version": manifest.version,
        }

    return {
        "hash": h,
        "error": result.get("error", {}).get("message", "Unknown error"),
        "name": manifest.name,
        "version": manifest.version,
    }


def pull_agent(ref: str, registry_url: str = "") -> AgentManifest | None:
    """Pull an .agent manifest from the Noether registry by stage ID.

    The ref can be:
    - A Noether stage ID (hex hash from registry)
    - A search query (will find first matching agent:* stage)
    """
    url = registry_url or _registry_url()
    if not url:
        raise ValueError("No registry URL configured")

    # Try direct ID lookup first
    result = _request("GET", f"{url}/stages/{ref}")
    if result.get("ok") is not False:
        data = result.get("data", result)
        stage = data.get("stage", data)
        return _stage_to_manifest(stage)

    # Try search
    result = _request("GET", f"{url}/stages/search?q={ref}")
    if result.get("ok") is not False:
        data = result.get("data", result)
        results = data.get("results", [])
        # Find first agent-manifest result
        for r in results:
            if "agent-manifest" in r.get("tags", []):
                stage_id = r.get("id", "")
                if stage_id:
                    detail = _request("GET", f"{url}/stages/{stage_id}")
                    if detail.get("ok") is not False:
                        d = detail.get("data", detail)
                        s = d.get("stage", d)
                        return _stage_to_manifest(s)

    return None


def search_agents(
    query: str, registry_url: str = "", limit: int = 20
) -> list[dict[str, Any]]:
    """Search for .agent manifests in the Noether registry."""
    url = registry_url or _registry_url()
    if not url:
        raise ValueError("No registry URL configured")

    # Search with agentspec tag filter
    result = _request("GET", f"{url}/stages/search?q=agent {query}")
    if result.get("ok") is False:
        return []

    data = result.get("data", result)
    results = data.get("results", [])

    agents = []
    for r in results:
        tags = r.get("tags", [])
        if "agent-manifest" in tags or "agentspec" in tags:
            name = r.get("description", r.get("name", "")).replace("Agent: ", "")
            agents.append({
                "id": r.get("id", ""),
                "name": name,
                "description": r.get("description", ""),
                "tags": tags,
                "score": r.get("score", ""),
            })

    return agents[:limit]
