#!/usr/bin/env python3
"""Export an agent profile as JSON (for publishing to registry).

Input:  { agent_id: str, profiles_dir: str? }
Output: { profile: AgentProfile }
"""
import sys, json
sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.profile.manager import ProfileManager

data = json.load(sys.stdin)
agent_id = data["agent_id"]
profiles_dir = data.get("profiles_dir", "/tmp/agentspec-profiles")

try:
    mgr = ProfileManager(profiles_dir)
    profile = mgr.load_profile(agent_id)
    if not profile:
        json.dump({"error": f"Profile not found: {agent_id}"}, sys.stdout)
        sys.exit(0)

    json.dump({
        "profile": profile.model_dump(),
        "summary": {
            "agent_id": profile.agent_id,
            "agent_hash": profile.agent_hash,
            "total_sprints": profile.total_sprints(),
            "completion_rate": profile.completion_rate(),
            "total_memories": len(profile.memories),
            "validated_memories": len(profile.validated_memories()),
            "total_skills": len(profile.skills),
            "top_skills": [s.skill for s in profile.top_skills(5)],
        },
    }, sys.stdout)
except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
