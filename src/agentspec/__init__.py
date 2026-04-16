"""AgentSpec — Universal Agent Manifest Standard with Resolver."""

from agentspec.parser.manifest import (
    AgentManifest,
    AuthProvider,
    AuthSpec,
    BehaviorSpec,
    ExposedMethod,
    MemorySpec,
    MergeSpec,
    ModelSpec,
    ObservabilitySpec,
    PipelineStep,
    SubAgentRef,
    ToolsSpec,
    TrustSpec,
)
from agentspec.parser.loader import load_agent, agent_hash, export_schema
from agentspec.resolver.resolver import resolve, ResolvedPlan
from agentspec.resolver.merger import resolve_inheritance
from agentspec.resolver.vertex import VertexConfig, detect_vertex_ai

__all__ = [
    "AgentManifest",
    "AuthProvider",
    "AuthSpec",
    "BehaviorSpec",
    "ExposedMethod",
    "MemorySpec",
    "MergeSpec",
    "ModelSpec",
    "ObservabilitySpec",
    "PipelineStep",
    "ResolvedPlan",
    "SubAgentRef",
    "ToolsSpec",
    "TrustSpec",
    "VertexConfig",
    "agent_hash",
    "detect_vertex_ai",
    "export_schema",
    "load_agent",
    "resolve",
    "resolve_inheritance",
]

__version__ = "0.3.3"
