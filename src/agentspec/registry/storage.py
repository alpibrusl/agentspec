"""Filesystem-backed, tenant-scoped storage for the agent registry.

Layout:

    {base_dir}/
      tenants/
        {tenant}/
          agents/
            {safe_hash}.json
          index.json

Authenticated operations are scoped to a tenant: ``alice`` cannot see
``bob``'s manifests, and delete/get return ``None`` across tenants.
Anonymous reads (``tenant=None``) probe every tenant directory so the
public catalog still works without an API key — matching the "public
reads, scoped writes" model in server.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest

REGISTRY_DIR_ENV = "AGENTSPEC_REGISTRY_DIR"
DEFAULT_REGISTRY_DIR = "/data/registry"
REGISTRY_DIR = os.environ.get(REGISTRY_DIR_ENV, DEFAULT_REGISTRY_DIR)


class RegistryStorage:
    """Filesystem registry for agent manifests, tenant-scoped."""

    def __init__(self, base_dir: str | None = None):
        # Read the env at __init__ time, not at import, so tests that
        # monkeypatch AGENTSPEC_REGISTRY_DIR per-function get isolation.
        if base_dir is None:
            base_dir = os.environ.get(REGISTRY_DIR_ENV, DEFAULT_REGISTRY_DIR)
        self.base_dir = Path(base_dir)
        self.tenants_dir = self.base_dir / "tenants"
        self.tenants_dir.mkdir(parents=True, exist_ok=True)

    def _tenant_root(self, tenant: str) -> Path:
        d = self.tenants_dir / tenant
        (d / "agents").mkdir(parents=True, exist_ok=True)
        return d

    def _load_index(self, root: Path) -> dict[str, Any]:
        idx = root / "index.json"
        if idx.exists():
            return json.loads(idx.read_text())
        return {}

    def _save_index(self, root: Path, index: dict[str, Any]) -> None:
        (root / "index.json").write_text(json.dumps(index, indent=2))

    def save_agent(self, manifest: AgentManifest, *, tenant: str) -> str:
        """Store a manifest under ``tenant``. Returns its content-addressable hash."""
        h = agent_hash(manifest)
        safe_name = h.replace(":", "_")

        root = self._tenant_root(tenant)
        (root / "agents" / f"{safe_name}.json").write_text(
            manifest.model_dump_json(indent=2)
        )

        index = self._load_index(root)
        index[h] = {
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description or "",
            "tags": manifest.tags,
            "author": manifest.author or "",
            "tenant": tenant,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_index(root, index)
        return h

    def _read_manifest(self, root: Path, ref: str) -> AgentManifest | None:
        safe_name = ref.replace(":", "_")
        p = root / "agents" / f"{safe_name}.json"
        if not p.exists():
            return None
        return AgentManifest.model_validate_json(p.read_text())

    def _iter_tenants(self) -> list[Path]:
        if not self.tenants_dir.exists():
            return []
        return [p for p in self.tenants_dir.iterdir() if p.is_dir()]

    def get_agent(
        self, ref: str, *, tenant: str | None = None
    ) -> AgentManifest | None:
        """Fetch a manifest by hash.

        When ``tenant`` is given, only that tenant's store is searched.
        When ``tenant`` is ``None`` (anonymous read), every tenant is
        probed until a match is found.
        """
        if tenant is not None:
            return self._read_manifest(self._tenant_root(tenant), ref)

        for t_dir in self._iter_tenants():
            found = self._read_manifest(t_dir, ref)
            if found is not None:
                return found
        return None

    def delete_agent(self, ref: str, *, tenant: str) -> bool:
        """Remove a manifest from ``tenant``'s store. Returns False if the
        manifest does not exist in that tenant (even if another tenant has
        the same hash) — so cross-tenant deletes surface as 404."""
        root = self._tenant_root(tenant)
        safe_name = ref.replace(":", "_")
        p = root / "agents" / f"{safe_name}.json"
        if not p.exists():
            return False
        p.unlink()
        index = self._load_index(root)
        index.pop(ref, None)
        self._save_index(root, index)
        return True

    def list_agents(
        self,
        q: str = "",
        tag: str = "",
        page: int = 1,
        limit: int = 50,
        *,
        tenant: str | None = None,
    ) -> dict[str, Any]:
        """Search and list agents. Returns {agents: [...], total: N}.

        When ``tenant`` is given, only that tenant's index is scanned.
        When ``tenant`` is ``None``, every tenant's index is aggregated.
        """
        items: list[dict[str, Any]] = []

        if tenant is not None:
            idx = self._load_index(self._tenant_root(tenant))
            items = [{"hash": h, **meta} for h, meta in idx.items()]
        else:
            for t_dir in self._iter_tenants():
                idx = self._load_index(t_dir)
                items.extend({"hash": h, **meta} for h, meta in idx.items())

        results = []
        for item in items:
            if q:
                text = f"{item.get('name', '')} {item.get('description', '')}".lower()
                if q.lower() not in text:
                    continue
            if tag and tag not in item.get("tags", []):
                continue
            results.append(item)

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        total = len(results)
        start = (page - 1) * limit
        return {
            "agents": results[start : start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
