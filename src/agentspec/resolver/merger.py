"""Merger — inheritance engine with enforced merge strategies.

This is the feature missing from all existing agent standards.
Merge semantics are explicit and enforced — not git-fork semantics.

Key invariant: ``trust: restrict`` is hardcoded. A child agent can never
escalate permissions beyond its parent.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from agentspec.parser.loader import load_agent
from agentspec.parser.manifest import (
    AgentManifest,
    MergeSpec,
    TrustSpec,
    FS_ORDER,
    NET_ORDER,
    EXEC_ORDER,
)


class TrustEscalationError(Exception):
    """Raised when a child agent tries to escalate trust beyond its parent."""


def resolve_inheritance(manifest: AgentManifest) -> AgentManifest:
    """Resolve the full inheritance chain.

    If manifest has a ``base``, load it (recursively) and merge
    according to the declared merge strategy.
    """
    if not manifest.base:
        return manifest

    # Resolve relative base paths from the source file's directory
    base_dir = Path(manifest._source_dir) if manifest._source_dir else None
    parent = load_agent(manifest.base, _base_dir=base_dir)
    parent = resolve_inheritance(parent)

    merged = _merge(parent, manifest, manifest.merge)
    _assert_trust_restriction(manifest.trust, parent.trust)
    return merged


def _merge(parent: AgentManifest, child: AgentManifest, merge: MergeSpec) -> AgentManifest:
    result = deepcopy(parent)

    # ── Skills ────────────────────────────────────────────────────────────
    if merge.skills == "append":
        result.skills = _dedup(parent.skills + child.skills)
    elif merge.skills == "override":
        result.skills = child.skills
    elif merge.skills == "restrict":
        result.skills = [s for s in child.skills if s in parent.skills]

    # ── Tools ─────────────────────────────────────────────────────────────
    if merge.tools == "append":
        result.tools.mcp = _dedup_tools(parent.tools.mcp + child.tools.mcp)
        result.tools.native = _dedup(parent.tools.native + child.tools.native)
    elif merge.tools == "override":
        result.tools = child.tools
    elif merge.tools == "restrict":
        parent_mcp_names = {_tool_name(t) for t in parent.tools.mcp}
        result.tools.mcp = [t for t in child.tools.mcp if _tool_name(t) in parent_mcp_names]
        result.tools.native = [t for t in child.tools.native if t in parent.tools.native]

    # ── Behavior ──────────────────────────────────────────────────────────
    if merge.behavior == "override":
        result.behavior = child.behavior
    elif merge.behavior == "append":
        result.behavior = deepcopy(parent.behavior)
        result.behavior.traits = _dedup(parent.behavior.traits + child.behavior.traits)
        if child.behavior.temperature != 0.5:
            result.behavior.temperature = child.behavior.temperature
        if child.behavior.max_steps != 20:
            result.behavior.max_steps = child.behavior.max_steps
        if child.behavior.persona:
            result.behavior.persona = child.behavior.persona

    # ── Soul/Rules — child overrides if present ───────────────────────────
    if child.soul:
        result.soul = child.soul
    if child.rules:
        result.rules = child.rules

    # ── Trust — always restrict ───────────────────────────────────────────
    result.trust = _merge_trust_restrictive(parent.trust, child.trust)

    # ── Observability — child overrides ───────────────────────────────────
    result.observability = child.observability

    # ── Meta — child always wins ──────────────────────────────────────────
    result.name = child.name
    result.version = child.version
    result.description = child.description or parent.description
    result.author = child.author or parent.author
    result.base = child.base
    result.merge = child.merge

    # ── Extensions — deep merge ───────────────────────────────────────────
    merged_ext = {**parent.extensions}
    for key, val in child.extensions.items():
        if key in merged_ext and isinstance(merged_ext[key], dict) and isinstance(val, dict):
            merged_ext[key] = {**merged_ext[key], **val}
        else:
            merged_ext[key] = val
    result.extensions = merged_ext

    return result


def _merge_trust_restrictive(parent: TrustSpec, child: TrustSpec) -> TrustSpec:
    """Pick the MORE restrictive value for each trust dimension."""
    return TrustSpec(
        filesystem=_more_restrictive(child.filesystem, parent.filesystem, FS_ORDER),
        network=_more_restrictive(child.network, parent.network, NET_ORDER),
        exec=_more_restrictive(child.exec, parent.exec, EXEC_ORDER),
        scope=child.scope or parent.scope,
    )


def _more_restrictive(a: str, b: str, order: list[str]) -> str:
    return a if order.index(a) <= order.index(b) else b


def _assert_trust_restriction(child: TrustSpec, parent: TrustSpec) -> None:
    if not child.is_at_least_as_restrictive_as(parent):
        raise TrustEscalationError(
            f"Trust escalation violation: child agent cannot have more permissions "
            f"than parent. Child: filesystem={child.filesystem}, network={child.network}, "
            f"exec={child.exec}. Parent: filesystem={parent.filesystem}, "
            f"network={parent.network}, exec={parent.exec}"
        )


def _dedup(lst: list[str]) -> list[str]:
    return list(dict.fromkeys(lst))


def _tool_name(tool: str | dict[str, object]) -> str:
    if isinstance(tool, str):
        return tool
    return next(iter(tool.keys()))


def _dedup_tools(lst: list[str | dict[str, object]]) -> list[str | dict[str, object]]:
    seen: set[str] = set()
    result: list[str | dict[str, object]] = []
    for item in lst:
        key = _tool_name(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
