"""Pydantic models — source of truth for the .agent schema.

All models use ``extra = "ignore"`` for forward compatibility:
unknown fields are silently dropped, never errored.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Model ──────────────────────────────────────────────────────────────────────


class ModelSpec(BaseModel, extra="ignore"):
    capability: Literal[
        "reasoning-low", "reasoning-mid", "reasoning-high", "reasoning-max"
    ] = "reasoning-mid"
    preferred: list[str] = []
    fallback: Optional[str] = None
    context: Union[Literal["full"], str] = "full"


# ── Auth ───────────────────────────────────────────────────────────────────────


class AuthProvider(BaseModel, extra="ignore"):
    from_: Optional[str] = Field(None, alias="from")

    model_config = {"populate_by_name": True}


class AuthSpec(BaseModel, extra="ignore"):
    strategy: Literal["auto", "explicit", "none"] = "auto"
    providers: dict[str, AuthProvider] = {}


# ── Tools ──────────────────────────────────────────────────────────────────────


class DependencySpec(BaseModel, extra="ignore"):
    """Declares what needs to be installed for a tool or skill to work."""

    pip: list[str] = []
    npm: list[str] = []
    cargo: list[str] = []
    nix: list[str] = []
    setup: list[str] = []
    env: dict[str, str] = {}


class McpServerSpec(BaseModel, extra="ignore"):
    """Structured MCP server specification.

    Accepted in ``tools.mcp`` alongside plain strings and legacy dicts.
    Plain strings are expanded via the well-known server registry at
    provision time; legacy ``{name: {config}}`` dicts are normalised
    into this shape by the provisioner.
    """

    name: str
    url: Optional[str] = None
    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: Optional[str] = None
    args: list[str] = []
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    requires: DependencySpec = DependencySpec()


class SkillSpec(BaseModel, extra="ignore"):
    """Enriched skill with optional dependency declaration.

    Skills can be plain strings (``web-search``) or dicts with a
    ``name`` key and optional ``requires``. Plain strings are the
    common case; enriched skills are for orchestrators that need
    to install dependencies before running.
    """

    name: str
    requires: DependencySpec = DependencySpec()


class ToolsSpec(BaseModel, extra="ignore"):
    mcp: list[Union[str, dict[str, Any]]] = []
    native: list[str] = []


# ── Memory ─────────────────────────────────────────────────────────────────────


class MemorySpec(BaseModel, extra="ignore"):
    working: Literal["session", "none"] = "session"
    long_term: Literal["none", "local", "external"] = "none"
    shared: bool = False


# ── Behavior ───────────────────────────────────────────────────────────────────


class BehaviorSpec(BaseModel, extra="ignore"):
    persona: Optional[str] = None
    traits: list[str] = []
    temperature: float = 0.5
    max_steps: int = 20
    on_error: Literal["ask", "retry", "fail", "skip"] = "ask"
    system_override: Optional[str] = None


# ── Expose ─────────────────────────────────────────────────────────────────────


class ExposedMethod(BaseModel, extra="ignore"):
    name: str
    description: Optional[str] = None
    input: dict[str, str] = {}
    output: Optional[str] = None


# ── Trust ──────────────────────────────────────────────────────────────────────

FS_ORDER = ["none", "read-only", "scoped", "full"]
NET_ORDER = ["none", "scoped", "allowed"]
EXEC_ORDER = ["none", "sandboxed", "full"]


class TrustSpec(BaseModel, extra="ignore"):
    filesystem: Literal["none", "read-only", "scoped", "full"] = "none"
    network: Literal["none", "allowed", "scoped"] = "none"
    exec: Literal["none", "sandboxed", "full"] = "none"
    scope: list[str] = []

    def is_at_least_as_restrictive_as(self, other: TrustSpec) -> bool:
        """Enforce trust-restrict invariant: self (child) must be <= other (parent)."""
        return (
            FS_ORDER.index(self.filesystem) <= FS_ORDER.index(other.filesystem)
            and NET_ORDER.index(self.network) <= NET_ORDER.index(other.network)
            and EXEC_ORDER.index(self.exec) <= EXEC_ORDER.index(other.exec)
        )


# ── Observability ──────────────────────────────────────────────────────────────


class ObservabilitySpec(BaseModel, extra="ignore"):
    trace: bool = False
    cost_limit: Optional[float] = None
    step_limit: int = 50
    on_exceed: Literal["ask", "abort"] = "abort"


# ── Merge strategy ─────────────────────────────────────────────────────────────


class MergeSpec(BaseModel, extra="ignore"):
    skills: Literal["append", "override", "restrict"] = "append"
    tools: Literal["append", "override", "restrict"] = "append"
    behavior: Literal["override", "append"] = "override"
    trust: Literal["restrict"] = "restrict"  # hardcoded — cannot be changed


# ── Multi-agent pipeline ──────────────────────────────────────────────────────


class SubAgentRef(BaseModel, extra="ignore"):
    ref: str
    role: Literal["subagent", "orchestrator", "validator"] = "subagent"


class PipelineStep(BaseModel, extra="ignore"):
    call: str
    output: Optional[str] = None


# ── Root manifest ──────────────────────────────────────────────────────────────


class AgentManifest(BaseModel, extra="ignore"):
    apiVersion: str = "agent/v1"
    name: str
    version: str = "0.1.0"
    author: Optional[str] = None
    license: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = []

    # Inheritance
    base: Optional[str] = None
    merge: MergeSpec = MergeSpec()

    # Core
    model: ModelSpec = ModelSpec()
    auth: AuthSpec = AuthSpec()
    skills: list[Union[str, dict[str, Any]]] = []
    tools: ToolsSpec = ToolsSpec()
    memory: MemorySpec = MemorySpec()
    behavior: BehaviorSpec = BehaviorSpec()
    expose: list[ExposedMethod] = []
    trust: TrustSpec = TrustSpec()
    observability: ObservabilitySpec = ObservabilitySpec()

    # Multi-agent
    agents: dict[str, SubAgentRef] = {}
    pipeline: list[PipelineStep] = []

    # Runtime-specific extensions — ignored by other runtimes
    extensions: dict[str, Any] = {}

    # Directory format extras (populated by loader, not in YAML)
    soul: Optional[str] = None
    rules: Optional[str] = None

    # Internal: source directory for resolving relative base paths (not in YAML)
    _source_dir: Optional[str] = None
