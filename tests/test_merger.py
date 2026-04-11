"""Tests for the merger — inheritance engine with trust enforcement."""

from pathlib import Path

import pytest

from agentspec.parser.loader import load_agent
from agentspec.parser.manifest import (
    AgentManifest,
    BehaviorSpec,
    MergeSpec,
    ModelSpec,
    ToolsSpec,
    TrustSpec,
)
from agentspec.resolver.merger import (
    TrustEscalationError,
    resolve_inheritance,
    _merge,
    _merge_trust_restrictive,
)


EXAMPLES = Path(__file__).parent.parent / "examples"


class TestMergeSkills:
    def test_append(self):
        parent = AgentManifest(name="parent", skills=["a", "b"])
        child = AgentManifest(name="child", skills=["b", "c"], merge=MergeSpec(skills="append"))
        result = _merge(parent, child, child.merge)
        assert result.skills == ["a", "b", "c"]

    def test_override(self):
        parent = AgentManifest(name="parent", skills=["a", "b"])
        child = AgentManifest(name="child", skills=["x"], merge=MergeSpec(skills="override"))
        result = _merge(parent, child, child.merge)
        assert result.skills == ["x"]

    def test_restrict(self):
        parent = AgentManifest(name="parent", skills=["a", "b", "c"])
        child = AgentManifest(name="child", skills=["b", "d"], merge=MergeSpec(skills="restrict"))
        result = _merge(parent, child, child.merge)
        assert result.skills == ["b"]  # only b is in parent


class TestMergeTools:
    def test_append_mcp(self):
        parent = AgentManifest(
            name="parent",
            tools=ToolsSpec(mcp=["github"], native=["bash"]),
        )
        child = AgentManifest(
            name="child",
            tools=ToolsSpec(mcp=["linear", "github"], native=["browser"]),
            merge=MergeSpec(tools="append"),
        )
        result = _merge(parent, child, child.merge)
        assert "github" in result.tools.mcp
        assert "linear" in result.tools.mcp
        assert len(result.tools.mcp) == 2  # deduped
        assert "bash" in result.tools.native
        assert "browser" in result.tools.native

    def test_restrict_tools(self):
        parent = AgentManifest(
            name="parent",
            tools=ToolsSpec(mcp=["github", "linear"], native=["bash"]),
        )
        child = AgentManifest(
            name="child",
            tools=ToolsSpec(mcp=["github", "slack"], native=["bash", "browser"]),
            merge=MergeSpec(tools="restrict"),
        )
        result = _merge(parent, child, child.merge)
        assert result.tools.mcp == ["github"]
        assert result.tools.native == ["bash"]


class TestMergeBehavior:
    def test_override(self):
        parent = AgentManifest(
            name="parent",
            behavior=BehaviorSpec(persona="parent-persona", traits=["a", "b"]),
        )
        child = AgentManifest(
            name="child",
            behavior=BehaviorSpec(persona="child-persona", traits=["c"]),
            merge=MergeSpec(behavior="override"),
        )
        result = _merge(parent, child, child.merge)
        assert result.behavior.persona == "child-persona"
        assert result.behavior.traits == ["c"]

    def test_append(self):
        parent = AgentManifest(
            name="parent",
            behavior=BehaviorSpec(traits=["a", "b"], temperature=0.5),
        )
        child = AgentManifest(
            name="child",
            behavior=BehaviorSpec(traits=["b", "c"], temperature=0.2),
            merge=MergeSpec(behavior="append"),
        )
        result = _merge(parent, child, child.merge)
        assert result.behavior.traits == ["a", "b", "c"]
        assert result.behavior.temperature == 0.2


class TestTrustMerge:
    def test_always_restricts(self):
        parent_trust = TrustSpec(filesystem="full", network="allowed", exec="full")
        child_trust = TrustSpec(filesystem="scoped", network="scoped", exec="sandboxed")
        result = _merge_trust_restrictive(parent_trust, child_trust)
        assert result.filesystem == "scoped"
        assert result.network == "scoped"
        assert result.exec == "sandboxed"

    def test_parent_more_restrictive_wins(self):
        parent_trust = TrustSpec(filesystem="none", network="none", exec="none")
        child_trust = TrustSpec(filesystem="full", network="allowed", exec="full")
        result = _merge_trust_restrictive(parent_trust, child_trust)
        assert result.filesystem == "none"
        assert result.network == "none"
        assert result.exec == "none"


class TestTrustEscalation:
    def test_escalation_raises(self):
        parent = AgentManifest(
            name="parent",
            trust=TrustSpec(filesystem="read-only", network="none", exec="none"),
        )
        child = AgentManifest(
            name="child",
            base="parent",
            trust=TrustSpec(filesystem="full", network="allowed", exec="full"),
        )
        with pytest.raises(TrustEscalationError, match="Trust escalation"):
            from agentspec.resolver.merger import _assert_trust_restriction
            _assert_trust_restriction(child.trust, parent.trust)


class TestInheritanceChain:
    def test_legal_researcher_inherits(self):
        """The legal-researcher extends researcher — real file test."""
        m = load_agent(EXAMPLES / "legal-researcher.agent")
        resolved = resolve_inheritance(m)
        assert resolved.name == "legal-researcher"
        # Should have parent's skills + no new skills (behavior=override)
        assert "web-search" in resolved.skills
        assert "cite-sources" in resolved.skills
        # Should have child's MCP tools appended
        mcp_names = [t if isinstance(t, str) else list(t.keys())[0] for t in resolved.tools.mcp]
        assert "courtlistener" in mcp_names
        assert "google-scholar" in mcp_names

    def test_meta_child_wins(self):
        parent = AgentManifest(name="parent", version="1.0.0", description="Parent desc")
        child = AgentManifest(name="child", version="2.0.0")
        result = _merge(parent, child, MergeSpec())
        assert result.name == "child"
        assert result.version == "2.0.0"
        assert result.description == "Parent desc"  # child didn't override

    def test_extensions_deep_merge(self):
        parent = AgentManifest(
            name="parent",
            extensions={"x-claude": {"thinking": True}, "x-shared": {"a": 1}},
        )
        child = AgentManifest(
            name="child",
            extensions={"x-claude": {"grounding": True}, "x-new": {"b": 2}},
        )
        result = _merge(parent, child, MergeSpec())
        assert result.extensions["x-claude"] == {"thinking": True, "grounding": True}
        assert result.extensions["x-shared"] == {"a": 1}
        assert result.extensions["x-new"] == {"b": 2}
