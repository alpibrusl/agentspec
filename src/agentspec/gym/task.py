"""Task fixtures for the gym.

A Task describes a single evaluation: a goal prompt given to the agent
plus a list of assertions used to score the resulting worktree. Tasks
are stored as YAML under ``corpus/`` and discovered by relative path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Task:
    """A gym task fixture."""

    id: str
    goal: str
    assertions: list[dict[str, Any]] = field(default_factory=list)
    setup: dict[str, Any] = field(default_factory=dict)
    timeout_s: int = 180

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        required = {"id", "goal"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Task missing required fields: {sorted(missing)}")
        return cls(
            id=data["id"],
            goal=data["goal"],
            assertions=data.get("assertions", []),
            setup=data.get("setup", {}),
            timeout_s=int(data.get("timeout_s", 180)),
        )


def load_task(path: str | Path) -> Task:
    """Load a task from a YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Task not found: {p}")
    data = yaml.safe_load(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Task YAML must be a mapping, got {type(data).__name__}: {p}")
    return Task.from_dict(data)
