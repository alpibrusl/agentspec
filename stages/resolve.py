#!/usr/bin/env python3
"""Resolve an agent manifest against the current environment.

Input:  { manifest: AgentManifest | path: str, verbose: bool? }
Output: { runtime: str, model: str, tools: [], missing_tools: [], auth_source: str,
          system_prompt_length: int, warnings: [], decisions: [] }

Reads environment: checks PATH for runtimes, env vars for API keys.
"""
import sys
import json

sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.parser.manifest import AgentManifest
from agentspec.parser.loader import load_agent
from agentspec.resolver.resolver import resolve

data = json.load(sys.stdin)
verbose = data.get("verbose", True)

try:
    if "manifest" in data:
        manifest = AgentManifest(**data["manifest"])
    elif "path" in data:
        manifest = load_agent(data["path"])
    else:
        json.dump({"error": "No manifest or path provided"}, sys.stdout)
        sys.exit(0)

    plan = resolve(manifest, verbose=verbose)
    json.dump(plan.to_dict(), sys.stdout)

except RuntimeError as e:
    json.dump({"error": str(e), "runtime": None, "model": None}, sys.stdout)
except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
