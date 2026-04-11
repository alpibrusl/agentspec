"""Loader — reads .agent files and agent directories.

Supports two equivalent formats:
- Single file: ``researcher.agent`` or ``agent.yaml``
- Directory: ``researcher/`` containing ``agent.yaml`` + optional ``SOUL.md`` + ``RULES.md``

Auto-detects format from the path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from agentspec.parser.manifest import AgentManifest


def load_agent(path: str | Path, *, _base_dir: Path | None = None) -> AgentManifest:
    """Load a .agent file or agent directory. Auto-detects format.

    ``_base_dir`` is used internally to resolve relative ``base:`` references
    from the directory of the file that declared them.
    """
    path = Path(path)

    # Resolve relative paths from the base directory of the referring file
    if _base_dir and not path.is_absolute():
        path = _base_dir / path

    if path.is_dir():
        return _load_directory(path)
    if path.suffix == ".agent" or path.name in ("agent.yaml", "agent.yml"):
        return _load_file(path)

    raise ValueError(f"Unknown agent format: {path}. Expected .agent file or directory.")


def _load_file(path: Path) -> AgentManifest:
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")
    raw = yaml.safe_load(path.read_text())
    if not raw:
        raise ValueError(f"Empty agent file: {path}")
    manifest = AgentManifest(**(raw or {}))
    manifest._source_dir = str(path.resolve().parent)
    return manifest


def _load_directory(path: Path) -> AgentManifest:
    """Load agent from directory format (agent.yaml + SOUL.md + RULES.md)."""
    manifest_path = path / "agent.yaml"
    if not manifest_path.exists():
        manifest_path = path / "agent.yml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No agent.yaml found in directory: {path}")

    raw: dict[str, Any] = yaml.safe_load(manifest_path.read_text()) or {}

    soul_path = path / "SOUL.md"
    if soul_path.exists():
        raw["soul"] = soul_path.read_text()

    rules_path = path / "RULES.md"
    if rules_path.exists():
        raw["rules"] = rules_path.read_text()

    manifest = AgentManifest(**raw)
    manifest._source_dir = str(path.resolve())
    return manifest


def agent_hash(manifest: AgentManifest) -> str:
    """Content-addressable hash for registry storage."""
    import json
    data = manifest.model_dump(mode="json")
    content = json.dumps(data, sort_keys=True)
    return "ag1:" + hashlib.sha256(content.encode()).hexdigest()[:12]


def export_schema() -> dict[str, Any]:
    """Export JSON Schema — auto-generated from Pydantic models."""
    return AgentManifest.model_json_schema()
