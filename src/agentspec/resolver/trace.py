"""Structured account of what the resolver did.

Companion to ``ResolvedPlan.decisions`` (free-text). The free-text trail
exists for humans reading ``--verbose`` output; the structured trail
exists so a future agent or audit tool can answer questions like
"which models were tried before this one?" or "did Vertex routing
fire?" without parsing English.

Both are populated from the same code paths in ``resolver.resolver``,
so they cannot drift.

The trace is persisted on ``ExecutionRecord.resolver_trace`` (signed
along with the rest of the record). All sub-models use
``extra="forbid"`` so a typo in a future writer can't silently corrupt
records read by older code — same convention as ``ExecutionRecord``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RuntimeDetection(BaseModel):
    """One row of the runtime PATH probe."""

    model_config = ConfigDict(extra="forbid")
    name: str
    available: bool


class VertexRouting(BaseModel):
    """Vertex AI was detected and (potentially) used to route a model."""

    model_config = ConfigDict(extra="forbid")
    project: str
    location: str
    used: bool = Field(
        default=False,
        description=(
            "True iff the selected model was actually routed through "
            "Vertex (i.e. provider supports Vertex routing). False when "
            "Vertex was detected but the chosen provider went direct."
        ),
    )


CandidateOutcome = Literal["selected", "skipped"]


class ModelCandidate(BaseModel):
    """One entry from ``manifest.model.preferred`` plus the verdict.

    Exactly one entry across ``ModelSelection.candidates`` should have
    ``outcome == "selected"`` for a successful resolve; the rest carry
    a ``skip_reason`` so an audit can see why each was passed over.
    """

    model_config = ConfigDict(extra="forbid")
    model: str
    provider: str
    runtime: Optional[str] = Field(
        default=None,
        description="Mapped runtime name; None when the provider prefix is unknown.",
    )
    outcome: CandidateOutcome
    skip_reason: Optional[str] = Field(
        default=None,
        description="One-line reason; populated when outcome == 'skipped'.",
    )
    auth_source: Optional[str] = Field(
        default=None,
        description=(
            "How the runtime authenticates: ``env.<KEY>``, "
            "``vertex-ai:<location>``, ``<runtime> subscription``, "
            "or ``local socket``. Populated when outcome == 'selected'."
        ),
    )


class ModelSelection(BaseModel):
    """The resolver's full attempt to satisfy ``manifest.model.preferred``.

    When the preferred list is exhausted and ``manifest.model.fallback``
    is set, the resolver retries with capability-tier defaults; the
    fallback chain's candidates are appended to ``candidates`` and
    ``fallback_capability_used`` records which tier kicked in.
    """

    model_config = ConfigDict(extra="forbid")
    candidates: list[ModelCandidate] = Field(default_factory=list)
    selected_model: Optional[str] = None
    selected_runtime: Optional[str] = None
    selected_auth_source: Optional[str] = None
    fallback_capability_used: Optional[str] = Field(
        default=None,
        description=(
            "Set to the capability tier (e.g. 'reasoning-high') when the "
            "preferred list was exhausted and ``manifest.model.fallback`` "
            "kicked in."
        ),
    )


SkillOutcome = Literal["resolved", "missing", "builtin", "passthrough"]


class SkillResolution(BaseModel):
    """Per-skill verdict: which concrete tool (if any) backed an abstract skill."""

    model_config = ConfigDict(extra="forbid")
    skill: str
    outcome: SkillOutcome
    resolved_to: Optional[str] = Field(
        default=None,
        description="Tool name the skill resolved to; populated when outcome == 'resolved'.",
    )
    candidates: list[str] = Field(
        default_factory=list,
        description="Ordered list of tools the resolver considered (from SKILL_MAP).",
    )


class McpToolResolution(BaseModel):
    """Pass-through record for a declared MCP tool.

    The resolver does not validate MCP tools at resolve time — the
    runtime verifies them at spawn. This record exists so the trace
    is complete (every declared tool accounted for).
    """

    model_config = ConfigDict(extra="forbid")
    name: str
    outcome: Literal["registered"] = "registered"


class ResolverTrace(BaseModel):
    """Machine-readable account of how a manifest became a plan.

    Persisted on ``ExecutionRecord.resolver_trace``. Empty defaults are
    fine when a plan is constructed outside the resolver (some tests,
    future hand-built plans) — the field will serialise as an empty
    structure rather than ``null``.
    """

    model_config = ConfigDict(extra="forbid")
    runtimes_detected: list[RuntimeDetection] = Field(default_factory=list)
    vertex: Optional[VertexRouting] = None
    model_selection: ModelSelection = Field(default_factory=ModelSelection)
    skills: list[SkillResolution] = Field(default_factory=list)
    mcp_tools: list[McpToolResolution] = Field(default_factory=list)
