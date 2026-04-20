"""Tests for the resolver — environment negotiation engine."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentspec.parser.loader import load_agent
from agentspec.parser.manifest import AgentManifest, ModelSpec
from agentspec.resolver.resolver import (
    ResolvedPlan,
    _build_system_prompt,
    _capability_defaults,
    _detect_runtimes,
    _query_llm_here_detect,
    _resolve_skills,
    resolve,
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


class TestLlmHereIntegration:
    """Behaviour of `_detect_runtimes` when `llm-here` is/isn't installed."""

    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_absent_returns_none(self, mock_which):
        # Pretend `llm-here` is not on PATH.
        mock_which.side_effect = lambda binary: None if binary == "llm-here" else "/usr/bin/other"
        result = _query_llm_here_detect()
        assert result is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_present_but_crashes_returns_none(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["llm-here"], timeout=5.0)
        assert _query_llm_here_detect() is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_non_zero_exit_returns_none(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="kaboom")
        assert _query_llm_here_detect() is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_invalid_json_returns_none(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(returncode=0, stdout="not json at all")
        assert _query_llm_here_detect() is None

    @pytest.mark.parametrize("payload", ["[]", "null", '"string"', "42"])
    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_non_object_json_returns_none(
        self, mock_which, mock_run, payload
    ):
        # Valid JSON but not the documented dict-with-providers shape —
        # a future schema change or wire corruption would hit this. Must
        # fall through to local detection, not raise AttributeError.
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(returncode=0, stdout=payload)
        assert _query_llm_here_detect() is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_providers_not_a_list_returns_none(self, mock_which, mock_run):
        # `providers` present but wrong type (object instead of array).
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"providers": {"claude-cli": true}}',
        )
        assert _query_llm_here_detect() is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_malformed_provider_entries_are_skipped(
        self, mock_which, mock_run
    ):
        # Individual non-dict entries inside `providers` must not raise.
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "providers": [
                        "not a dict",
                        None,
                        42,
                        {"id": "claude-cli", "kind": "cli"},
                    ]
                }
            ),
        )
        result = _query_llm_here_detect()
        assert result is not None
        assert result["claude-code"] is True

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_permission_error_returns_none(self, mock_which, mock_run):
        # Binary on PATH but not executable (rare but happens with
        # broken packaging). Must fall through to local detection.
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.side_effect = PermissionError(13, "Permission denied")
        assert _query_llm_here_detect() is None

    @patch("agentspec.resolver.resolver.subprocess.run")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_llm_here_translates_provider_ids_to_agentspec_names(self, mock_which, mock_run):
        # `llm-here detect` reports 2 of the 4 shared CLIs as reachable.
        # We expect _query_llm_here_detect to translate the ids back to
        # the agentspec runtime names with a stable dict shape.
        mock_which.return_value = "/usr/bin/llm-here"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "schema_version": 1,
                    "tool_version": "0.4.0",
                    "cli_detection_skipped": False,
                    "providers": [
                        {"id": "claude-cli", "kind": "cli", "binary": "/usr/local/bin/claude"},
                        {"id": "gemini-cli", "kind": "cli", "binary": "/usr/bin/gemini"},
                        # An API provider (not a CLI) — must be ignored.
                        {"id": "anthropic-api", "kind": "api", "env": "ANTHROPIC_API_KEY"},
                    ],
                }
            ),
        )
        result = _query_llm_here_detect()
        assert result is not None
        # Exactly the 4 shared-CLI keys, translated to agentspec names.
        assert set(result.keys()) == {"claude-code", "gemini-cli", "cursor-cli", "opencode"}
        # Reported values reflect llm-here output.
        assert result["claude-code"] is True
        assert result["gemini-cli"] is True
        assert result["cursor-cli"] is False
        assert result["opencode"] is False

    @patch("agentspec.resolver.resolver._query_llm_here_detect")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_detect_falls_back_to_local_when_llm_here_absent(self, mock_which, mock_query):
        mock_query.return_value = None
        # Pretend codex is installed, claude is not.
        mock_which.side_effect = lambda b: "/usr/bin/codex" if b == "codex" else None
        result = _detect_runtimes()
        assert result["codex-cli"] is True
        assert result["claude-code"] is False
        # All keys from RUNTIME_BINARIES are present regardless.
        assert "aider" in result
        assert "ollama" in result

    @patch("agentspec.resolver.resolver._query_llm_here_detect")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_detect_upgrades_false_to_true_via_llm_here(self, mock_which, mock_query):
        # Local detection says claude is absent (not on Python's PATH),
        # but llm-here found it in its own lookup path (e.g. per-user
        # ~/.local/bin that wasn't exported to this shell). llm-here
        # can upgrade False → True.
        mock_which.return_value = None
        mock_query.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor-cli": False,
            "opencode": False,
        }
        result = _detect_runtimes()
        assert result["claude-code"] is True
        # Non-shared runtimes still fall back to shutil.which (False here).
        assert result["codex-cli"] is False
        assert result["ollama"] is False

    @patch("agentspec.resolver.resolver._query_llm_here_detect")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_detect_does_not_downgrade_true_to_false(self, mock_which, mock_query):
        # Binary is on Python's PATH (shutil.which returns a hit), but
        # llm-here's registry lookup didn't find it (e.g. installed to
        # a path llm-here doesn't probe). agentspec must keep the
        # local True — union semantics, not override, so the merge is
        # monotonic. Regression guard for the "not a strict improvement"
        # issue raised on PR #29.
        mock_which.side_effect = (
            lambda b: "/usr/bin/claude" if b == "claude" else None
        )
        mock_query.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor-cli": False,
            "opencode": False,
        }
        result = _detect_runtimes()
        assert result["claude-code"] is True, (
            "llm-here must not downgrade a locally-detected True to False"
        )

    def test_llm_here_map_keys_are_all_registered_runtimes(self):
        # Drift guard: every agentspec name in _LLM_HERE_CLI_IDS must
        # also be a key in RUNTIME_BINARIES. If someone adds a new
        # llm-here mapping without also registering the runtime
        # locally, the override loop would inject a name the rest of
        # the resolver doesn't recognise.
        from agentspec.resolver.resolver import (
            _LLM_HERE_CLI_IDS,
            RUNTIME_BINARIES,
        )
        unknown = set(_LLM_HERE_CLI_IDS) - set(RUNTIME_BINARIES)
        assert not unknown, (
            f"llm-here map has entries not in RUNTIME_BINARIES: {unknown}. "
            f"Register the runtime locally or drop the mapping."
        )

    @patch("agentspec.resolver.resolver._query_llm_here_detect")
    @patch("agentspec.resolver.resolver.shutil.which")
    def test_detect_preserves_non_shared_detection_when_llm_here_present(
        self, mock_which, mock_query
    ):
        # llm-here reports the 4 shared CLIs. Local detection is the
        # source of truth for everything else.
        mock_query.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor-cli": False,
            "opencode": False,
        }
        # Simulate ollama being installed locally.
        mock_which.side_effect = lambda b: "/usr/bin/ollama" if b == "ollama" else None
        result = _detect_runtimes()
        assert result["ollama"] is True
        assert result["claude-code"] is False


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
