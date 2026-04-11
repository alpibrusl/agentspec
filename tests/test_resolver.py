"""Tests for the resolver — environment negotiation engine."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agentspec.parser.loader import load_agent
from agentspec.parser.manifest import AgentManifest, ModelSpec
from agentspec.resolver.resolver import (
    ResolvedPlan,
    resolve,
    _build_system_prompt,
    _capability_defaults,
    _detect_runtimes,
    _resolve_skills,
)


EXAMPLES = Path(__file__).parent.parent / "examples"


class TestRuntimeDetection:
    def test_detect_returns_dict(self):
        runtimes = _detect_runtimes()
        assert isinstance(runtimes, dict)
        assert "claude-code" in runtimes
        assert "ollama" in runtimes

    def test_all_values_are_bool(self):
        runtimes = _detect_runtimes()
        for v in runtimes.values():
            assert isinstance(v, bool)


class TestCapabilityDefaults:
    def test_known_capabilities(self):
        for cap in ["reasoning-low", "reasoning-mid", "reasoning-high", "reasoning-max"]:
            defaults = _capability_defaults(cap)
            assert len(defaults) > 0

    def test_unknown_capability(self):
        assert _capability_defaults("unknown") == []


class TestSkillResolution:
    def test_builtin_skill_no_tool(self):
        decisions: list[str] = []
        resolved, missing = _resolve_skills(["summarize"], decisions)
        assert resolved == []
        assert missing == []
        assert any("built-in" in d for d in decisions)

    def test_unknown_skill_passthrough(self):
        decisions: list[str] = []
        resolved, missing = _resolve_skills(["custom-skill"], decisions)
        assert "custom-skill" in resolved
        assert any("unknown" in d for d in decisions)


class TestSystemPrompt:
    def test_persona_and_traits(self):
        from agentspec.parser.manifest import BehaviorSpec
        m = AgentManifest(
            name="test",
            behavior=BehaviorSpec(
                persona="researcher",
                traits=["cite-everything", "never-guess"],
            ),
        )
        prompt = _build_system_prompt(m)
        assert "researcher" in prompt
        assert "cite" in prompt.lower()
        assert "fabricate" in prompt.lower()

    def test_soul_takes_priority(self):
        from agentspec.parser.manifest import BehaviorSpec
        m = AgentManifest(
            name="test",
            soul="# Custom Soul\nYou are unique.",
            behavior=BehaviorSpec(persona="ignored"),
        )
        prompt = _build_system_prompt(m)
        assert "Custom Soul" in prompt
        assert "ignored" not in prompt

    def test_rules_always_appended(self):
        m = AgentManifest(
            name="test",
            soul="# Soul",
            rules="# Rules\n- Never lie",
        )
        prompt = _build_system_prompt(m)
        assert "Soul" in prompt
        assert "Never lie" in prompt

    def test_system_override_fallback(self):
        from agentspec.parser.manifest import BehaviorSpec
        m = AgentManifest(
            name="test",
            behavior=BehaviorSpec(system_override="You are a custom bot."),
        )
        prompt = _build_system_prompt(m)
        assert "custom bot" in prompt


class TestResolverPlan:
    def test_to_dict(self):
        plan = ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            tools=["bash"],
            auth_source="env.ANTHROPIC_API_KEY",
            system_prompt="test",
        )
        d = plan.to_dict()
        assert d["runtime"] == "claude-code"
        assert d["model"] == "claude/claude-sonnet-4-6"
        assert d["system_prompt_length"] == 4


class TestResolverIntegration:
    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_resolve_with_claude(self, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = load_agent(EXAMPLES / "researcher.agent")
        plan = resolve(m, verbose=True)
        assert plan.runtime == "claude-code"
        assert "claude" in plan.model
        assert plan.auth_source == "env.ANTHROPIC_API_KEY"
        assert len(plan.decisions) > 0

    @patch("agentspec.resolver.resolver._detect_runtimes")
    def test_resolve_no_runtime_raises(self, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = load_agent(EXAMPLES / "researcher.agent")
        with pytest.raises(RuntimeError, match="No model could be resolved"):
            resolve(m)

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_fallback_to_gemini(self, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": True,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = load_agent(EXAMPLES / "researcher.agent")
        plan = resolve(m)
        assert plan.runtime == "gemini-cli"
        assert "gemini" in plan.model

    @patch("agentspec.resolver.resolver._detect_runtimes")
    def test_fallback_to_local(self, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": True,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(
                capability="reasoning-mid",
                preferred=["local/llama3:70b"],
            ),
        )
        plan = resolve(m)
        assert plan.runtime == "ollama"
        assert "llama3" in plan.model

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_directory_agent_resolve(self, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = load_agent(EXAMPLES / "researcher")
        plan = resolve(m)
        assert plan.runtime == "claude-code"
        # SOUL.md should be in system prompt
        assert "precise" in plan.system_prompt.lower()
        # RULES.md should be appended
        assert "Must Never" in plan.system_prompt
