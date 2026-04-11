#!/usr/bin/env python3
"""Process sprint retro into agent profile memories + portfolio.

Input:  { agent_id: str, feedback: {...}, sprint_id: str, project: str?, profiles_dir: str? }
Output: { memories_added: int, memories_signed: int, skills_added: int, ... }

feedback: { assessment: str, clarity: int, blockers: [str], tools: [str], notes: str, time_s: int }
"""
import sys, json
sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.profile.manager import ProfileManager

data = json.load(sys.stdin)
agent_id = data["agent_id"]
feedback = data["feedback"]
sprint_id = data.get("sprint_id", "unknown")
project = data.get("project", "")
profiles_dir = data.get("profiles_dir", "/tmp/agentspec-profiles")

try:
    mgr = ProfileManager(profiles_dir)
    profile = mgr.load_profile(agent_id)
    if not profile:
        json.dump({"error": f"Profile not found: {agent_id}"}, sys.stdout)
        sys.exit(0)

    result = mgr.process_retro(profile, feedback, sprint_id, project)
    json.dump(result, sys.stdout)
except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
