"""Regression tests for the two issues reported against v0.2.1:

1. opencode provider was skipped by the resolver (unknown provider 'opencode')
2. claude-code runner crashed when no --input was provided (--print with empty prompt)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentspec.parser.manifest import AgentManifest, BehaviorSpec, ModelSpec
from agentspec.resolver.resolver import ResolvedPlan, resolve
from agentspec.runner.runner import (
    _build_claude_cmd,
    _build_codex_cmd,
    _build_gemini_cmd,
    _build_opencode_cmd,
    _derive_prompt,
)


# ── Issue 1: opencode provider ────────────────────────────────────────────────


class TestOpencodeProvider:
    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {}, clear=True)
    def test_opencode_default_resolves_when_binary_present(self, mock_runtimes):
        """opencode/default should resolve when opencode is in PATH, even with no API keys."""
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": True,
            "aider": False,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(
                capability="reasoning-high",
                preferred=["opencode/default", "claude/claude-sonnet-4-6"],
            ),
        )
        plan = resolve(m, verbose=True)
        assert plan.runtime == "opencode"
        assert plan.model == "opencode/default"
        assert "local" in plan.auth_source or "socket" in plan.auth_source

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {}, clear=True)
    def test_opencode_skipped_when_binary_missing(self, mock_runtimes):
        """When opencode is NOT in PATH, the resolver moves to the next preferred."""
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
                preferred=["opencode/default", "local/llama3:8b"],
            ),
        )
        plan = resolve(m, verbose=True)
        assert plan.runtime == "ollama"

    @patch("agentspec.resolver.resolver._detect_runtimes")
    @patch.dict("os.environ", {}, clear=True)
    def test_aider_default_also_works(self, mock_runtimes):
        """aider/default should resolve without API keys (aider handles its own)."""
        mock_runtimes.return_value = {
            "claude-code": False,
            "gemini-cli": False,
            "cursor": False,
            "codex-cli": False,
            "opencode": False,
            "aider": True,
            "ollama": False,
        }
        m = AgentManifest(
            name="test",
            model=ModelSpec(preferred=["aider/default"]),
        )
        plan = resolve(m)
        assert plan.runtime == "aider"

    def test_opencode_cmd_uses_run_subcommand_with_positional_prompt(self):
        """Verify the runner builds `opencode run "{prompt}"`.

        Updated from the original ``opencode --print`` assertion after
        cross-checking the real CLI: opencode's non-interactive form
        per https://opencode.ai/docs/cli/ is the ``run`` subcommand,
        not ``--print``. Also matches caloron-noether's field-validated
        FRAMEWORKS table entry for opencode.
        """
        m = AgentManifest(
            name="x",
            description="test agent",
            behavior=BehaviorSpec(traits=["be-concise"]),
        )
        plan = ResolvedPlan(
            runtime="opencode",
            model="opencode/default",
            system_prompt="You are an x.",
        )
        cmd = _build_opencode_cmd(plan, m, "hello world")
        assert cmd[0:2] == ["opencode", "run"]
        # The prompt is a single positional argument — not split into --prompt
        assert len(cmd) == 3
        # System prompt is prepended to the user prompt
        assert "You are an x." in cmd[2]
        assert "hello world" in cmd[2]


# ── Issue 2: claude-code without --input ──────────────────────────────────────


class TestClaudeNoInputFallback:
    def test_soul_used_when_no_input(self):
        """Directory-format agent with SOUL.md → that content becomes the prompt."""
        m = AgentManifest(
            name="researcher",
            description="A short description",
            soul="# Deep Researcher\n\nYou cite everything.",
        )
        assert _derive_prompt(m, None) == "# Deep Researcher\n\nYou cite everything."

    def test_description_used_when_no_soul_no_input(self):
        """Single-file agent without SOUL.md → description becomes the prompt."""
        m = AgentManifest(name="x", description="Do the thing.")
        assert _derive_prompt(m, None) == "Do the thing."

    def test_explicit_input_wins(self):
        """--input takes precedence over SOUL.md or description."""
        m = AgentManifest(
            name="x",
            description="fallback",
            soul="also fallback",
        )
        assert _derive_prompt(m, "user said hi") == "user said hi"

    def test_empty_fallback_returns_none(self):
        """No input, no SOUL, no description → None. Caller decides what to do."""
        m = AgentManifest(name="bare")
        assert _derive_prompt(m, None) is None

    def test_claude_cmd_without_input_uses_description(self):
        """Regression: `agentspec run <dir>` (no --input) must not crash claude."""
        m = AgentManifest(name="x", description="Audit citations.")
        plan = ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            system_prompt="You are an auditor.",
        )
        cmd = _build_claude_cmd(plan, m, None)
        # `-p` is present (claude's --print form) AND has a value — not bare.
        assert "-p" in cmd
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "Audit citations."

    def test_claude_cmd_without_input_prefers_soul(self):
        """Directory agent with SOUL.md → claude prompt is SOUL content, not description."""
        m = AgentManifest(
            name="x",
            description="fallback",
            soul="You are SOUL.",
        )
        plan = ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
        )
        cmd = _build_claude_cmd(plan, m, None)
        assert "-p" in cmd
        assert cmd[cmd.index("-p") + 1] == "You are SOUL."

    def test_claude_cmd_no_prompt_at_all(self):
        """Bare manifest + no input → no -p flag (interactive mode)."""
        m = AgentManifest(name="bare")
        plan = ResolvedPlan(runtime="claude-code", model="claude/claude-haiku-4-5")
        cmd = _build_claude_cmd(plan, m, None)
        assert "-p" not in cmd

    def test_gemini_and_codex_use_same_fallback(self):
        """The same precedence must apply to gemini-cli and codex-cli."""
        m = AgentManifest(name="x", description="Do work.")
        plan_g = ResolvedPlan(runtime="gemini-cli", model="gemini/gemini-2.5-pro")
        plan_c = ResolvedPlan(runtime="codex-cli", model="openai/o3")

        gemini_cmd = _build_gemini_cmd(plan_g, m, None)
        assert "Do work." in gemini_cmd

        codex_cmd = _build_codex_cmd(plan_c, m, None)
        assert "Do work." in codex_cmd
