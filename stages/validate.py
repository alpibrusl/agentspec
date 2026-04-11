#!/usr/bin/env python3
"""Validate an agent manifest against the AgentSpec schema.

Input:  { manifest: AgentManifest | yaml_string: str | path: str }
Output: { valid: bool, name: str, version: str, hash: str, errors: [] }

Pure stage: no side effects.
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
    elif "yaml_string" in data:
        import yaml
        raw = yaml.safe_load(data["yaml_string"])
        manifest = AgentManifest(**raw)
    else:
        json.dump({"valid": False, "errors": ["No manifest, path, or yaml_string provided"]}, sys.stdout)
        sys.exit(0)

    h = agent_hash(manifest)
    json.dump({
        "valid": True,
        "name": manifest.name,
        "version": manifest.version,
        "hash": h,
        "apiVersion": manifest.apiVersion,
        "skills": manifest.skills,
        "has_base": manifest.base is not None,
        "errors": [],
    }, sys.stdout)

except Exception as e:
    json.dump({"valid": False, "errors": [str(e)]}, sys.stdout)
