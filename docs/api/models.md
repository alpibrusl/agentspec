# API: Models

Pydantic models defining the `.agent` schema.

## `AgentManifest`

Root model for `.agent` files.

```python
from agentspec import AgentManifest, load_agent

manifest = load_agent("my.agent")
print(manifest.name, manifest.version)
print(manifest.skills)
print(manifest.behavior.traits)
```

| Field | Type | Default |
|---|---|---|
| `apiVersion` | `str` | `"agent/v1"` |
| `name` | `str` | required |
| `version` | `str` | `"0.1.0"` |
| `author` | `str?` | `None` |
| `license` | `str?` | `None` |
| `description` | `str?` | `None` |
| `tags` | `list[str]` | `[]` |
| `base` | `str?` | `None` |
| `merge` | `MergeSpec` | `MergeSpec()` |
| `model` | `ModelSpec` | `ModelSpec()` |
| `auth` | `AuthSpec` | `AuthSpec()` |
| `skills` | `list[str]` | `[]` |
| `tools` | `ToolsSpec` | `ToolsSpec()` |
| `memory` | `MemorySpec` | `MemorySpec()` |
| `behavior` | `BehaviorSpec` | `BehaviorSpec()` |
| `expose` | `list[ExposedMethod]` | `[]` |
| `trust` | `TrustSpec` | `TrustSpec()` |
| `observability` | `ObservabilitySpec` | `ObservabilitySpec()` |
| `agents` | `dict[str, SubAgentRef]` | `{}` |
| `pipeline` | `list[PipelineStep]` | `[]` |
| `extensions` | `dict[str, Any]` | `{}` |
| `soul` | `str?` | `None` (loaded from SOUL.md) |
| `rules` | `str?` | `None` (loaded from RULES.md) |

Forward compatibility: unknown fields ignored (`extra = "ignore"`).

## `ModelSpec`

```python
class ModelSpec:
    capability: Literal["reasoning-low", "reasoning-mid", "reasoning-high", "reasoning-max"]
    preferred: list[str]
    fallback: Optional[str]
    context: Union[Literal["full"], str]
```

## `BehaviorSpec`

```python
class BehaviorSpec:
    persona: Optional[str]
    traits: list[str]
    temperature: float = 0.5
    max_steps: int = 20
    on_error: Literal["ask", "retry", "fail", "skip"] = "ask"
    system_override: Optional[str]
```

## `TrustSpec`

```python
class TrustSpec:
    filesystem: Literal["none", "read-only", "scoped", "full"] = "none"
    network: Literal["none", "allowed", "scoped"] = "none"
    exec: Literal["none", "sandboxed", "full"] = "none"
    scope: list[str]

    def is_at_least_as_restrictive_as(self, other: TrustSpec) -> bool:
        ...
```

## `MergeSpec`

```python
class MergeSpec:
    skills: Literal["append", "override", "restrict"] = "append"
    tools: Literal["append", "override", "restrict"] = "append"
    behavior: Literal["override", "append"] = "override"
    trust: Literal["restrict"] = "restrict"   # hardcoded
```

## Loading

```python
from agentspec import load_agent, agent_hash, export_schema

manifest = load_agent("path/to/file.agent")
manifest = load_agent("path/to/agent_dir/")
hash_str = agent_hash(manifest)              # ag1:xxx
schema = export_schema()                     # JSON Schema dict
```
