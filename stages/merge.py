#!/usr/bin/env python3
"""Merge a child agent manifest with its parent (inheritance).

Input:  { child: AgentManifest, parent: AgentManifest }
   or:  { child_path: str }  (loads child, resolves base: chain automatically)
Output: { merged: AgentManifest, trust_ok: bool }

Enforces trust-restrict invariant: child cannot escalate parent permissions.
"""
import sys
import json

sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.parser.manifest import AgentManifest
from agentspec.parser.loader import load_agent
from agentspec.resolver.merger import resolve_inheritance, TrustEscalationError

data = json.load(sys.stdin)

try:
    if "child_path" in data:
        child = load_agent(data["child_path"])
        merged = resolve_inheritance(child)
    elif "child" in data and "parent" in data:
        child = AgentManifest(**data["child"])
        parent = AgentManifest(**data["parent"])
        from agentspec.resolver.merger import _merge, _assert_trust_restriction
        merged = _merge(parent, child, child.merge)
        _assert_trust_restriction(child.trust, parent.trust)
    else:
        json.dump({"error": "Provide child_path or (child + parent)"}, sys.stdout)
        sys.exit(0)

    json.dump({
        "merged": merged.model_dump(exclude_none=True),
        "trust_ok": True,
    }, sys.stdout)

except TrustEscalationError as e:
    json.dump({"error": str(e), "trust_ok": False}, sys.stdout)
except Exception as e:
    json.dump({"error": str(e)}, sys.stdout)
