"""FastAPI registry server for AgentSpec.

Run with: uvicorn agentspec.registry.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.registry.storage import RegistryStorage

app = FastAPI(
    title="AgentSpec Registry",
    description="Push, pull, and search universal agent manifests",
    version="0.1.0",
)

storage = RegistryStorage()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/agents", status_code=201)
def push_agent(manifest: AgentManifest) -> dict[str, str]:
    """Push an agent manifest to the registry."""
    h = storage.save_agent(manifest)
    return {
        "hash": h,
        "name": manifest.name,
        "version": manifest.version,
    }


@app.get("/v1/agents/{ref}")
def pull_agent(ref: str) -> Any:
    """Pull an agent manifest by hash."""
    # URL path encodes : as %3A, FastAPI decodes it
    manifest = storage.get_agent(ref)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Agent not found: {ref}")
    return JSONResponse(content={
        "hash": ref,
        "manifest": manifest.model_dump(exclude_none=True),
    })


@app.get("/v1/agents")
def list_agents(
    q: str = Query("", description="Search query"),
    tag: str = Query("", description="Filter by tag"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Search and list agents in the registry."""
    return storage.list_agents(q=q, tag=tag, page=page, limit=limit)


@app.delete("/v1/agents/{ref}")
def delete_agent(ref: str) -> dict[str, Any]:
    """Remove an agent from the registry."""
    if not storage.delete_agent(ref):
        raise HTTPException(status_code=404, detail=f"Agent not found: {ref}")
    return {"deleted": ref}
