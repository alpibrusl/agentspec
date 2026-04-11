"""Filesystem-backed storage for the agent registry.

Stores manifests as JSON files keyed by content-addressable hash (ag1:xxx).
An index.json provides fast search/list without scanning all files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest

REGISTRY_DIR = os.environ.get("AGENTSPEC_REGISTRY_DIR", "/data/registry")


class RegistryStorage:
    """Filesystem registry for agent manifests."""

    def __init__(self, base_dir: str = REGISTRY_DIR):
        self.base_dir = Path(base_dir)
        self.agents_dir = self.base_dir / "agents"
        self.index_path = self.base_dir / "index.json"
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {}

    def _save_index(self, index: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(index, indent=2))

    def save_agent(self, manifest: AgentManifest) -> str:
        """Store a manifest. Returns its content-addressable hash."""
        h = agent_hash(manifest)
        safe_name = h.replace(":", "_")

        # Write manifest JSON
        agent_file = self.agents_dir / f"{safe_name}.json"
        agent_file.write_text(manifest.model_dump_json(indent=2))

        # Update index
        index = self._load_index()
        index[h] = {
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description or "",
            "tags": manifest.tags,
            "author": manifest.author or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_index(index)

        return h

    def get_agent(self, ref: str) -> AgentManifest | None:
        """Fetch a manifest by hash (ag1:xxx)."""
        safe_name = ref.replace(":", "_")
        agent_file = self.agents_dir / f"{safe_name}.json"
        if not agent_file.exists():
            return None
        return AgentManifest.model_validate_json(agent_file.read_text())

    def delete_agent(self, ref: str) -> bool:
        """Remove a manifest from the registry."""
        safe_name = ref.replace(":", "_")
        agent_file = self.agents_dir / f"{safe_name}.json"
        if not agent_file.exists():
            return False
        agent_file.unlink()
        index = self._load_index()
        index.pop(ref, None)
        self._save_index(index)
        return True

    def list_agents(
        self,
        q: str = "",
        tag: str = "",
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search and list agents. Returns {agents: [...], total: N}."""
        index = self._load_index()
        results = []

        for h, meta in index.items():
            # Filter by query (substring match on name + description)
            if q:
                text = f"{meta.get('name', '')} {meta.get('description', '')}".lower()
                if q.lower() not in text:
                    continue
            # Filter by tag
            if tag and tag not in meta.get("tags", []):
                continue

            results.append({"hash": h, **meta})

        # Sort by created_at descending
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        total = len(results)
        start = (page - 1) * limit
        return {
            "agents": results[start : start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
