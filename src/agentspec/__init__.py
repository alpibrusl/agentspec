"""AgentSpec — Universal Agent Manifest Standard with Resolver."""

from agentspec.parser.manifest import (
    AgentManifest,
    AuthProvider,
    AuthSpec,
    BehaviorSpec,
    DependencySpec,
    ExposedMethod,
    McpServerSpec,
    MemorySpec,
    MergeSpec,
    ModelSpec,
    ObservabilitySpec,
    PipelineStep,
    SkillSpec,
    SubAgentRef,
    ToolsSpec,
    TrustSpec,
)
from agentspec.parser.loader import load_agent, agent_hash, export_schema
from agentspec.resolver.resolver import resolve, ResolvedPlan
from agentspec.resolver.merger import resolve_inheritance
from agentspec.resolver.vertex import VertexConfig, detect_vertex_ai
from agentspec.runner.provisioner import provision, provision_install

__all__ = [
    "AgentManifest",
    "AuthProvider",
    "AuthSpec",
    "BehaviorSpec",
    "DependencySpec",
    "ExposedMethod",
    "McpServerSpec",
    "MemorySpec",
    "MergeSpec",
    "ModelSpec",
    "ObservabilitySpec",
    "PipelineStep",
    "ResolvedPlan",
    "SkillSpec",
    "SubAgentRef",
    "ToolsSpec",
    "TrustSpec",
    "VertexConfig",
    "agent_hash",
    "detect_vertex_ai",
    "export_schema",
    "load_agent",
    "provision",
    "provision_install",
    "resolve",
    "resolve_inheritance",
]

__version__ = "0.4.1"
