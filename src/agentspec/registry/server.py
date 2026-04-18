"""FastAPI registry server for AgentSpec with multi-tenant auth.

Run with: uvicorn agentspec.registry.server:app --host 0.0.0.0 --port 8080

Configuration
-------------

Two ways to supply credentials, matching the noether-cloud registry model:

- ``AGENTSPEC_API_KEYS="alice:k1,bob:k2"`` — multi-tenant. The portion
  before the first colon is the tenant ID; the remainder is the API key.
  Each tenant has an isolated view: ``alice`` cannot pull, delete, or list
  ``bob``'s manifests when authenticated.

- ``AGENTSPEC_API_KEY="secret"`` — legacy single-tenant. The key is
  mapped to tenant ``default``. Ignored when ``AGENTSPEC_API_KEYS`` is
  also set (multi wins).

Mutating endpoints (``POST /v1/agents``, ``DELETE /v1/agents/{ref}``)
require the ``X-API-Key`` header and reject mismatches with HTTP 401.
Read endpoints remain public: anonymous callers see the aggregated
catalog across all tenants. When a read includes a valid ``X-API-Key``,
it is scoped to that caller's tenant.

For local development only, set ``AGENTSPEC_ALLOW_UNAUTHENTICATED=1``
to disable auth entirely (writes land in the ``default`` tenant).
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from agentspec.parser.manifest import AgentManifest
from agentspec.registry.storage import RegistryStorage

log = logging.getLogger(__name__)

API_KEY_ENV = "AGENTSPEC_API_KEY"
API_KEYS_ENV = "AGENTSPEC_API_KEYS"
ALLOW_UNAUTH_ENV = "AGENTSPEC_ALLOW_UNAUTHENTICATED"
DEFAULT_TENANT = "default"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
# Tenant IDs become directory names under {base}/tenants/{tenant}/, so
# they must not contain path separators or leading dots. Restrict to a
# conservative ASCII set — matches noether-cloud's tenant ID convention.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _auth_disabled() -> bool:
    return os.environ.get(ALLOW_UNAUTH_ENV, "").strip().lower() in _TRUTHY


def _parse_keys(raw: str) -> dict[str, str]:
    """Parse ``tenant1:key1,tenant2:key2`` into ``{key: tenant}``.

    Splits each entry on the first colon so keys may themselves contain
    colons. Blank entries and entries without a colon are dropped.
    """
    mapping: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        tenant, key = entry.split(":", 1)
        tenant = tenant.strip()
        key = key.strip()
        if not tenant or not key:
            continue
        if not _TENANT_ID_RE.match(tenant):
            log.warning(
                "Ignoring entry with invalid tenant ID %r — must match %s",
                tenant,
                _TENANT_ID_RE.pattern,
            )
            continue
        mapping[key] = tenant
    return mapping


def _key_to_tenant() -> dict[str, str]:
    """Get the current ``{key: tenant}`` mapping from env.

    ``AGENTSPEC_API_KEYS`` wins when both env vars are set. Legacy
    ``AGENTSPEC_API_KEY`` is mapped to tenant ``default``.
    """
    multi = os.environ.get(API_KEYS_ENV, "")
    if multi:
        return _parse_keys(multi)
    legacy = os.environ.get(API_KEY_ENV, "")
    if legacy:
        return {legacy: DEFAULT_TENANT}
    return {}


def _resolve_tenant(provided: str | None) -> str | None:
    """Return the tenant for a given API key, or ``None`` if unknown.

    Uses ``secrets.compare_digest`` so callers cannot distinguish "no
    such key" from "wrong key" via timing.
    """
    if not provided:
        return None
    mapping = _key_to_tenant()
    for key, tenant in mapping.items():
        if secrets.compare_digest(provided.encode(), key.encode()):
            return tenant
    return None


def require_tenant(x_api_key: str | None = Header(default=None)) -> str:
    """Dependency for mutating routes: resolve the caller's tenant.

    - ``AGENTSPEC_ALLOW_UNAUTHENTICATED=1`` → ``default`` tenant.
    - No keys configured at all → 503 (misconfigured).
    - Missing / unknown key → 401.
    """
    if _auth_disabled():
        return DEFAULT_TENANT

    mapping = _key_to_tenant()
    if not mapping:
        log.error(
            "%s and %s are both unset — refusing to authorise any write; "
            "configure one of them or set %s=1 for dev",
            API_KEYS_ENV,
            API_KEY_ENV,
            ALLOW_UNAUTH_ENV,
        )
        raise HTTPException(status_code=503, detail="registry misconfigured")

    tenant = _resolve_tenant(x_api_key)
    if tenant is None:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    return tenant


def optional_tenant(x_api_key: str | None = Header(default=None)) -> str | None:
    """Dependency for read routes: resolve the caller's tenant if any.

    Anonymous callers (no header) get ``None`` and see the aggregated
    public catalog. Authenticated callers get scoped to their tenant.
    An invalid key is treated as anonymous here — reads stay permissive
    by design. Use ``require_tenant`` for routes that must be strict.
    """
    if not x_api_key:
        return None
    return _resolve_tenant(x_api_key)


app = FastAPI(
    title="AgentSpec Registry",
    description="Push, pull, and search universal agent manifests (multi-tenant)",
    version="0.2.0",
)

storage = RegistryStorage()

# Startup-time sanity checks so misconfiguration is visible in logs
# before the first request discovers it.
if _auth_disabled():
    log.warning(
        "%s=1 — registry mutating endpoints are UNAUTHENTICATED. Dev-only.",
        ALLOW_UNAUTH_ENV,
    )
elif not (os.environ.get(API_KEYS_ENV) or os.environ.get(API_KEY_ENV)):
    log.error(
        "Neither %s nor %s is set — mutating endpoints will return 503 "
        "until configured",
        API_KEYS_ENV,
        API_KEY_ENV,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/agents", status_code=201)
def push_agent(
    manifest: AgentManifest,
    tenant: str = Depends(require_tenant),
) -> dict[str, str]:
    """Push an agent manifest to the caller's tenant."""
    h = storage.save_agent(manifest, tenant=tenant)
    return {
        "hash": h,
        "name": manifest.name,
        "version": manifest.version,
        "tenant": tenant,
    }


@app.get("/v1/agents/{ref}")
def pull_agent(
    ref: str,
    tenant: str | None = Depends(optional_tenant),
) -> Any:
    """Pull an agent manifest by hash.

    Authenticated callers see only their own tenant's manifests.
    Anonymous callers probe all tenants (public catalog).
    """
    manifest = storage.get_agent(ref, tenant=tenant)
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
    tenant: str | None = Depends(optional_tenant),
) -> dict[str, Any]:
    """Search and list agents. Scoped to caller's tenant if authenticated."""
    return storage.list_agents(q=q, tag=tag, page=page, limit=limit, tenant=tenant)


@app.delete("/v1/agents/{ref}")
def delete_agent(
    ref: str,
    tenant: str = Depends(require_tenant),
) -> dict[str, Any]:
    """Remove a manifest from the caller's tenant.

    Returns 404 if the manifest does not exist in this tenant, even when
    another tenant happens to host the same hash — cross-tenant deletes
    surface as "not found", never as "forbidden".
    """
    if not storage.delete_agent(ref, tenant=tenant):
        raise HTTPException(status_code=404, detail=f"Agent not found: {ref}")
    return {"deleted": ref, "tenant": tenant}
