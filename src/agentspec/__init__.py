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
    "agent_hash",
    "export_schema",
    "load_agent",
    "resolve",
    "resolve_inheritance",
]

__version__ = "0.1.0"
