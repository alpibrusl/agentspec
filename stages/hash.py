#!/usr/bin/env python3
"""Compute content-addressable hash of an agent manifest.

Input:  { manifest: AgentManifest | path: str }
Output: { hash: str, name: str, version: str }

Pure stage: deterministic, no side effects.
"""
import sys
import json

sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.parser.manifest import AgentManifest
from agentspec.parser.loader import load_agent, agent_hash

data = json.load(sys.stdin)

try:
    if "manifest" in data:
        manifest = AgentManifest(**data["manifest"])
    elif "path" in data:
        manifest = load_agent(data["path"])
    else:
        json.dump({"error": "No manifest or path provided"}, sys.stdout)
        sys.exit(0)

    h = agent_hash(manifest)
    json.dump({
        "hash": h,
        "name": manifest.name,
        "version": manifest.version,
    }, sys.stdout)

except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
