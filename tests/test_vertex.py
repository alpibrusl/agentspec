"""Tests for Vertex AI backend integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentspec.parser.manifest import AgentManifest, ModelSpec
from agentspec.resolver.resolver import resolve
from agentspec.resolver.vertex import (
    DEFAULT_LOCATION,
    VertexConfig,
    can_route_through_vertex,
    detect_vertex_ai,
    vertex_env_for_runtime,
)


# ── Detection ─────────────────────────────────────────────────────────────────


class TestDetection:
    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-proj"}, clear=True)
    def test_minimal_config(self, _adc):
        cfg = detect_vertex_ai()
        assert cfg is not None
        assert cfg.project == "my-proj"
        assert cfg.location == DEFAULT_LOCATION
        assert cfg.location == "europe-west1"

    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict(
        "os.environ",
        {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_CLOUD_LOCATION": "europe-west4"},
        clear=True,
    )
    def test_explicit_location(self, _adc):
        cfg = detect_vertex_ai()
        assert cfg.location == "europe-west4"

    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict(
        "os.environ",
        {
            "GOOGLE_CLOUD_PROJECT": "lo-priority",
            "AGENTSPEC_VERTEX_PROJECT": "hi-priority",
        },
        clear=True,
    )
    def test_explicit_agentspec_var_wins(self, _adc):
        cfg = detect_vertex_ai()
        assert cfg.project == "hi-priority"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_project_returns_none(self):
        assert detect_vertex_ai() is None

    @patch("agentspec.resolver.vertex._adc_available", return_value=False)
    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "p"}, clear=True)
    def test_no_adc_returns_none(self, _adc):
        assert detect_vertex_ai() is None


# ── Per-runtime env vars ──────────────────────────────────────────────────────


CFG = VertexConfig(project="my-project", location="europe-west1")


class TestEnvForRuntime:
    def test_claude_code(self):
        env = vertex_env_for_runtime("claude-code", CFG)
        assert env["CLAUDE_CODE_USE_VERTEX"] == "1"
        assert env["ANTHROPIC_VERTEX_PROJECT_ID"] == "my-project"
        assert env["CLOUD_ML_REGION"] == "europe-west1"
        assert env["GOOGLE_CLOUD_PROJECT"] == "my-project"

    def test_gemini_cli(self):
        env = vertex_env_for_runtime("gemini-cli", CFG)
        assert env["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
        assert env["GOOGLE_CLOUD_PROJECT"] == "my-project"
        assert env["GOOGLE_CLOUD_LOCATION"] == "europe-west1"

    def test_aider(self):
        env = vertex_env_for_runtime("aider", CFG)
        assert env["VERTEX_PROJECT"] == "my-project"
        assert env["VERTEX_LOCATION"] == "europe-west1"

    def test_opencode(self):
        env = vertex_env_for_runtime("opencode", CFG)
        assert env["GOOGLE_CLOUD_PROJECT"] == "my-project"
        assert env["GOOGLE_CLOUD_LOCATION"] == "europe-west1"

    def test_codex_cli_returns_empty(self):
        # OpenAI is not on Vertex Model Garden
        assert vertex_env_for_runtime("codex-cli", CFG) == {}

    def test_ollama_returns_empty(self):
        # Local model — no Vertex routing
        assert vertex_env_for_runtime("ollama", CFG) == {}


# ── Routing rules ─────────────────────────────────────────────────────────────


class TestRouting:
    def test_claude_routes_through_vertex(self):
        assert can_route_through_vertex("claude")
        assert can_route_through_vertex("anthropic")

    def test_gemini_routes_through_vertex(self):
        assert can_route_through_vertex("gemini")
        assert can_route_through_vertex("google")

    def test_openai_does_not_route(self):
        # OpenAI is not in Vertex Model Garden
        assert not can_route_through_vertex("openai")

    def test_local_does_not_route(self):
        assert not can_route_through_vertex("local")
        assert not can_route_through_vertex("ollama")


# ── Integration with resolver ─────────────────────────────────────────────────


class TestResolverIntegration:
    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict(
        "os.environ",
        {"GOOGLE_CLOUD_PROJECT": "my-vertex-project"},
        clear=True,
    )
    def test_claude_routes_through_vertex_when_configured(
        self, _adc, mock_runtimes
    ):
        mock_runtimes.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(
                capability="reasoning-high",
                preferred=["claude/claude-sonnet-4-6"],
            ),
        )
        plan = resolve(m, verbose=True)
        assert plan.runtime == "claude-code"
        assert "vertex-ai" in plan.auth_source.lower()
        assert "europe-west1" in plan.auth_source
        assert "my-vertex-project" in plan.auth_source

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict(
        "os.environ",
        {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_CLOUD_LOCATION": "europe-west4"},
        clear=True,
    )
    def test_custom_region(self, _adc, mock_runtimes):
        mock_runtimes.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(preferred=["gemini/gemini-2.0-pro"]),
        )
        # Even though gemini-cli not in PATH, the resolver will skip and try fallback
        # We just check that when reachable, region is europe-west4
        # Add gemini-cli to runtimes
        mock_runtimes.return_value["gemini-cli"] = True
        plan = resolve(m)
        assert "europe-west4" in plan.auth_source

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch("agentspec.resolver.vertex._adc_available", return_value=True)
    @patch.dict(
        "os.environ",
        {
            "GOOGLE_CLOUD_PROJECT": "p",
            "OPENAI_API_KEY": "sk-test",
        },
        clear=True,
    )
    def test_openai_does_not_use_vertex(self, _adc, mock_runtimes):
        # OpenAI/codex-cli must use direct API even when Vertex is configured
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": True,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(preferred=["openai/o3"]),
        )
        plan = resolve(m)
        assert plan.runtime == "codex-cli"
        assert "vertex" not in plan.auth_source.lower()
        assert "OPENAI_API_KEY" in plan.auth_source

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=True)
    def test_falls_back_to_direct_api_when_vertex_not_configured(
        self, mock_runtimes
    ):
        mock_runtimes.return_value = {
            "claude-code": True,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": False,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(preferred=["claude/claude-sonnet-4-6"]),
        )
        plan = resolve(m)
        assert plan.runtime == "claude-code"
        assert "ANTHROPIC_API_KEY" in plan.auth_source
        assert "vertex" not in plan.auth_source.lower()


# ── Runner env injection ──────────────────────────────────────────────────────


class TestRunnerEnv:
    @patch("agentspec.runner.runner.detect_vertex_ai")
    def test_build_env_injects_vertex_vars_when_vertex_picked(self, mock_detect):
        from agentspec.runner.runner import build_env
        from agentspec.resolver.resolver import ResolvedPlan

        mock_detect.return_value = VertexConfig(
            project="my-proj", location="europe-west1"
        )
        plan = ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            auth_source="vertex-ai (project=my-proj, region=europe-west1)",
        )
        env = build_env(plan)
        assert env["CLAUDE_CODE_USE_VERTEX"] == "1"
        assert env["ANTHROPIC_VERTEX_PROJECT_ID"] == "my-proj"
        assert env["CLOUD_ML_REGION"] == "europe-west1"

    @patch("agentspec.runner.runner.detect_vertex_ai")
    def test_build_env_no_vertex_vars_for_direct_api(self, mock_detect):
        from agentspec.runner.runner import build_env
        from agentspec.resolver.resolver import ResolvedPlan

        plan = ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            auth_source="env.ANTHROPIC_API_KEY",
        )
        env = build_env(plan)
        # Should NOT have called detect_vertex_ai or set Vertex vars
        mock_detect.assert_not_called()
        assert "CLAUDE_CODE_USE_VERTEX" not in env
