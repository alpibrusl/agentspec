"""FastAPI registry server for AgentSpec.

Run with: uvicorn agentspec.registry.server:app --host 0.0.0.0 --port 8080

Set ``AGENTSPEC_API_KEY`` to a non-empty value before starting. Mutating
endpoints (``POST /v1/agents``, ``DELETE /v1/agents/{ref}``) require the
``X-API-Key`` request header and reject mismatches with HTTP 401. Read
endpoints stay public. For local development only, set
``AGENTSPEC_ALLOW_UNAUTHENTICATED=1`` to skip the check (logs a warning).
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.registry.storage import RegistryStorage

log = logging.getLogger(__name__)

API_KEY_ENV = "AGENTSPEC_API_KEY"
ALLOW_UNAUTH_ENV = "AGENTSPEC_ALLOW_UNAUTHENTICATED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _auth_disabled() -> bool:
    return os.environ.get(ALLOW_UNAUTH_ENV, "").strip().lower() in _TRUTHY


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: validate the X-API-Key header.

    Returns silently on success. Raises 401 on mismatch or missing header.
    When ``AGENTSPEC_ALLOW_UNAUTHENTICATED=1`` is set, the check is
    skipped entirely and a warning is logged once per process start.
    """
    if _auth_disabled():
        return

    expected = os.environ.get(API_KEY_ENV, "")
    if not expected:
        log.error(
            "%s is not set — refusing to authorise any write; "
            "configure the env var or explicitly set %s=1 for dev",
            API_KEY_ENV,
            ALLOW_UNAUTH_ENV,
        )
        raise HTTPException(status_code=503, detail="registry misconfigured")

    provided = x_api_key or ""
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


app = FastAPI(
    title="AgentSpec Registry",
    description="Push, pull, and search universal agent manifests",
    version="0.1.0",
)

storage = RegistryStorage()

# Startup-time warning if the server key is missing. If the operator starts
# the server without AGENTSPEC_API_KEY, every write returns 503 from
# require_api_key; this line just surfaces the misconfiguration in logs
# before a caller discovers it the hard way.
if _auth_disabled():
    log.warning(
        "%s=1 — registry mutating endpoints are UNAUTHENTICATED. Dev-only.",
        ALLOW_UNAUTH_ENV,
    )
elif not os.environ.get(API_KEY_ENV):
    log.error(
        "%s is not set — mutating endpoints will return 503 until configured",
        API_KEY_ENV,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/agents", status_code=201, dependencies=[Depends(require_api_key)])
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


@app.delete("/v1/agents/{ref}", dependencies=[Depends(require_api_key)])
def delete_agent(ref: str) -> dict[str, Any]:
    """Remove an agent from the registry."""
    if not storage.delete_agent(ref):
        raise HTTPException(status_code=404, detail=f"Agent not found: {ref}")
    return {"deleted": ref}
