#!/usr/bin/env python3
"""Create an agent profile from a manifest.

Input:  { manifest: AgentManifest, profiles_dir: str? }
Output: { agent_id: str, agent_hash: str, profile_version: str }
"""
import sys, json
sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.parser.manifest import AgentManifest
from agentspec.profile.manager import ProfileManager

data = json.load(sys.stdin)
profiles_dir = data.get("profiles_dir", "/tmp/agentspec-profiles")

try:
    manifest = AgentManifest(**data["manifest"])
    mgr = ProfileManager(profiles_dir)
    profile = mgr.load_or_create(manifest)
    json.dump({
        "agent_id": profile.agent_id,
        "agent_hash": profile.agent_hash,
        "profile_version": profile.profile_version,
        "total_memories": len(profile.memories),
        "total_sprints": profile.total_sprints(),
    }, sys.stdout)
except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
