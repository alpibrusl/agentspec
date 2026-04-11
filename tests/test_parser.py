"""Tests for the parser — manifest models and loader."""

from pathlib import Path

import pytest
import yaml

from agentspec.parser.manifest import (
    AgentManifest,
    BehaviorSpec,
    MergeSpec,
    ModelSpec,
    TrustSpec,
)
from agentspec.parser.loader import load_agent, agent_hash, export_schema


EXAMPLES = Path(__file__).parent.parent / "examples"


# ── Manifest models ───────────────────────────────────────────────────────────


class TestManifest:
    def test_minimal_manifest(self):
        m = AgentManifest(name="test")
        assert m.name == "test"
        assert m.version == "0.1.0"
        assert m.apiVersion == "agent/v1"

    def test_full_manifest_from_dict(self):
        data = {
            "apiVersion": "agent/v1",
            "name": "full-agent",
            "version": "2.0.0",
            "description": "A complete agent",
            "tags": ["code", "test"],
            "model": {
                "capability": "reasoning-high",
                "preferred": ["claude/claude-sonnet-4-6"],
            },
            "skills": ["code-execution", "file-read"],
            "behavior": {
                "persona": "coder",
                "traits": ["think-step-by-step"],
                "temperature": 0.1,
            },
            "trust": {
                "filesystem": "scoped",
                "scope": ["./workspace"],
                "exec": "sandboxed",
            },
        }
        m = AgentManifest(**data)
        assert m.name == "full-agent"
        assert m.model.capability == "reasoning-high"
        assert m.trust.filesystem == "scoped"
        assert m.behavior.temperature == 0.1

    def test_extra_fields_ignored(self):
        """Forward compatibility: unknown fields are silently dropped."""
        m = AgentManifest(name="test", unknown_field="ignored", future_feature=True)
        assert m.name == "test"
        assert not hasattr(m, "unknown_field")

    def test_merge_trust_always_restrict(self):
        ms = MergeSpec()
        assert ms.trust == "restrict"
        # Cannot set to anything else
        with pytest.raises(Exception):
            MergeSpec(trust="override")


# ── Trust ─────────────────────────────────────────────────────────────────────


class TestTrust:
    def test_restrictive_comparison(self):
        parent = TrustSpec(filesystem="scoped", network="allowed", exec="sandboxed")
        child = TrustSpec(filesystem="read-only", network="scoped", exec="none")
        assert child.is_at_least_as_restrictive_as(parent)

    def test_escalation_detected(self):
        parent = TrustSpec(filesystem="read-only", network="none", exec="none")
        child = TrustSpec(filesystem="full", network="none", exec="none")
        assert not child.is_at_least_as_restrictive_as(parent)

    def test_equal_trust_is_ok(self):
        t = TrustSpec(filesystem="scoped", network="allowed", exec="sandboxed")
        assert t.is_at_least_as_restrictive_as(t)


# ── Loader ────────────────────────────────────────────────────────────────────


class TestLoader:
    def test_load_single_file(self):
        m = load_agent(EXAMPLES / "researcher.agent")
        assert m.name == "deep-researcher"
        assert m.version == "1.0.0"
        assert "web-search" in m.skills

    def test_load_coder(self):
        m = load_agent(EXAMPLES / "coder.agent")
        assert m.name == "senior-coder"
        assert m.trust.filesystem == "scoped"
        assert "bash" in m.tools.native

    def test_load_directory_format(self):
        m = load_agent(EXAMPLES / "researcher")
        assert m.name == "deep-researcher"
        assert m.soul is not None
        assert "precise" in m.soul.lower()
        assert m.rules is not None
        assert "Must Never" in m.rules

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_agent("/nonexistent/path.agent")

    def test_load_bad_format_raises(self):
        with pytest.raises(ValueError, match="Unknown agent format"):
            load_agent(Path(__file__))  # .py file

    def test_agent_hash_deterministic(self):
        m1 = load_agent(EXAMPLES / "researcher.agent")
        m2 = load_agent(EXAMPLES / "researcher.agent")
        assert agent_hash(m1) == agent_hash(m2)

    def test_agent_hash_differs(self):
        m1 = load_agent(EXAMPLES / "researcher.agent")
        m2 = load_agent(EXAMPLES / "coder.agent")
        assert agent_hash(m1) != agent_hash(m2)

    def test_export_schema(self):
        schema = export_schema()
        assert "properties" in schema
        assert "name" in schema["properties"]


# ── YAML round-trip ───────────────────────────────────────────────────────────


class TestYamlRoundTrip:
    def test_dump_and_reload(self, tmp_path):
        original = AgentManifest(
            name="roundtrip-test",
            version="1.0.0",
            skills=["web-search", "code-execution"],
            model=ModelSpec(capability="reasoning-high", preferred=["claude/claude-sonnet-4-6"]),
        )
        data = original.model_dump(exclude_none=True)
        out = tmp_path / "test.agent"
        out.write_text(yaml.dump(data, default_flow_style=False))

        reloaded = load_agent(out)
        assert reloaded.name == "roundtrip-test"
        assert reloaded.skills == ["web-search", "code-execution"]
