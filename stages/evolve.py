#!/usr/bin/env python3
"""Evolve an agent manifest based on retrospective data.

Input:  { manifest: AgentManifest | path: str, retro: RetroData, sprint_id: str }
Output: { evolved: AgentManifest | null, changes: [...], evolved_version: str | null }

RetroData: { avg_clarity: float, failure_rate: float, supervisor_events: int,
             avg_review_cycles: float, blockers: [str] }

Pure stage: produces new manifest, does not write files.
"""
import sys
import json

sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")
sys.path.insert(0, "/home/alpibru/workspace/caloron-noether/orchestrator")

from agentspec.parser.manifest import AgentManifest
from agentspec.parser.loader import load_agent, agent_hash

data = json.load(sys.stdin)
retro = data.get("retro", {})
sprint_id = data.get("sprint_id", "unknown")

try:
    if "manifest" in data:
        manifest = AgentManifest(**data["manifest"])
    elif "path" in data:
        manifest = load_agent(data["path"])
    else:
        json.dump({"error": "No manifest or path provided"}, sys.stdout)
        sys.exit(0)

    from agentspec_bridge import evolve_agent_manifest
    evolved, changes = evolve_agent_manifest(manifest, retro, {}, sprint_id)

    if evolved:
        json.dump({
            "evolved": evolved.model_dump(exclude_none=True),
            "evolved_version": evolved.version,
            "evolved_hash": agent_hash(evolved),
            "changes": [
                {
                    "field": c.field,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "reason": c.reason,
                    "agentspec_op": c.agentspec_op,
                }
                for c in changes
            ],
        }, sys.stdout)
    else:
        json.dump({
            "evolved": None,
            "evolved_version": None,
            "changes": [],
        }, sys.stdout)

except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
