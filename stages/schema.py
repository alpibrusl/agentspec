#!/usr/bin/env python3
"""Export the AgentSpec JSON Schema.

Input:  {}
Output: { schema: JSONSchema }

Pure stage: deterministic, no side effects.
"""
import sys
import json

sys.path.insert(0, "/home/alpibru/workspace/agentspec/src")

from agentspec.parser.loader import export_schema

json.dump({"schema": export_schema()}, sys.stdout)
