"""Structured ResolverTrace built alongside the free-text decision log.

The trace is the machine-readable companion to ``ResolvedPlan.decisions``;
it lets a future agent or audit tool answer questions like "which models
were tried before this one?" without parsing English. These tests pin the
shape end-to-end through ``resolve()`` and assert that hand-built plans
(no resolver) leave the trace as ``None`` so the runner persists ``null``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentspec.parser.manifest import (
    AgentManifest,
    ModelSpec,
    ToolsSpec,
    TrustSpec,
)
from agentspec.resolver.resolver import ResolvedPlan, resolve
from agentspec.resolver.trace import (
    McpToolResolution,
    ModelSelection,
    ResolverTrace,
    SkillResolution,
)


# ── helpers ───────────────────────────────────────────────────────────────────

# Runtime detection table that mirrors the production map but lets each test
# control which CLIs are "installed" without touching PATH or llm-here.
_ALL_RUNTIMES_OFF = {
    "claude-code": False,
    "gemini-cli": False,
    "codex-cli": False,
    "opencode": False,
    "goose": False,
    "aider": False,
    "ollama": False,
    "cursor-cli": False,
    "test-echo": False,
}


def _runtimes(**overrides: bool) -> dict[str, bool]:
    table = dict(_ALL_RUNTIMES_OFF)
    table.update(overrides)
    return table


@pytest.fixture
def clean_env(monkeypatch):
    """Strip provider env keys so the resolver's auth path is deterministic."""
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_GENAI_USE_VERTEXAI",
    ):
        monkeypatch.delenv(key, raising=False)


def _manifest(**kwargs) -> AgentManifest:
    defaults = dict(
        name="trace-test",
        model=ModelSpec(preferred=["claude/claude-sonnet-4-6"]),
        skills=[],
        tools=ToolsSpec(),
        trust=TrustSpec(filesystem="full", network="allowed", exec="full"),
    )
    defaults.update(kwargs)
    return AgentManifest(**defaults)


# ── ResolvedPlan default ──────────────────────────────────────────────────────


def test_resolved_plan_trace_defaults_to_none_for_hand_built_plans():
    """Hand-built plans (some tests, future hand-built callers) must serialise
    trace as None — runners persist null on the record, not an empty struct."""
    plan = ResolvedPlan(runtime="claude-code", model="claude/claude-sonnet-4-6")
    assert plan.trace is None
    assert plan.to_dict()["trace"] is None


# ── runtimes_detected ────────────────────────────────────────────────────────


def test_trace_records_every_runtime_with_availability(clean_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True, "ollama": True})
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(_manifest())

    names = {r.name: r.available for r in plan.trace.runtimes_detected}
    assert names["claude-code"] is True
    assert names["ollama"] is True
    assert names["gemini-cli"] is False
    assert set(names) == set(table)


# ── model_selection ──────────────────────────────────────────────────────────


def test_model_selection_records_skip_then_select(clean_env, monkeypatch):
    """Models earlier in the preferred list that fail must appear as skipped
    candidates with a reason — that's the whole point of the structured trail."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True})  # gemini-cli/codex-cli absent
    manifest = _manifest(
        model=ModelSpec(
            preferred=[
                "openai/gpt-4o",  # codex-cli not in PATH → skip
                "gemini/gemini-2.5-pro",  # gemini-cli not in PATH → skip
                "claude/claude-sonnet-4-6",  # selected
            ]
        )
    )
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    sel = plan.trace.model_selection
    assert [c.model for c in sel.candidates] == [
        "openai/gpt-4o",
        "gemini/gemini-2.5-pro",
        "claude/claude-sonnet-4-6",
    ]
    assert sel.candidates[0].outcome == "skipped"
    assert "codex-cli" in (sel.candidates[0].skip_reason or "")
    assert sel.candidates[1].outcome == "skipped"
    assert "gemini-cli" in (sel.candidates[1].skip_reason or "")
    assert sel.candidates[2].outcome == "selected"
    assert sel.candidates[2].auth_source == "env.ANTHROPIC_API_KEY"

    assert sel.selected_model == "claude/claude-sonnet-4-6"
    assert sel.selected_runtime == "claude-code"
    assert sel.selected_auth_source == "env.ANTHROPIC_API_KEY"
    assert sel.fallback_capability_used is None


def test_model_selection_records_unknown_provider_skip(clean_env):
    table = _runtimes(**{"ollama": True})
    manifest = _manifest(
        model=ModelSpec(preferred=["mystery/llm-7b", "local/llama3:8b"])
    )
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    candidates = plan.trace.model_selection.candidates
    assert candidates[0].outcome == "skipped"
    assert candidates[0].provider == "mystery"
    assert candidates[0].runtime is None
    assert "unknown provider" in (candidates[0].skip_reason or "")
    assert candidates[1].outcome == "selected"
    assert candidates[1].auth_source == "local socket"


def test_model_selection_subscription_path_recorded_when_no_env_key(
    clean_env, monkeypatch
):
    """claude-code/gemini-cli/codex-cli without env keys assume CLI login.
    The trace must mark this as 'selected' with an explicit subscription auth."""
    table = _runtimes(**{"claude-code": True})
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(_manifest())

    candidates = plan.trace.model_selection.candidates
    assert len(candidates) == 1
    assert candidates[0].outcome == "selected"
    assert candidates[0].auth_source == "claude-code subscription"


def test_model_selection_records_fallback_capability(clean_env, monkeypatch):
    """When the preferred list is exhausted and fallback kicks in, the trace
    records which capability tier produced the eventual selection."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True})
    manifest = _manifest(
        model=ModelSpec(
            preferred=["openai/gpt-4o"],  # codex-cli absent → exhausts preferred
            fallback="reasoning-high",  # default list contains a claude entry
        )
    )
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    sel = plan.trace.model_selection
    assert sel.fallback_capability_used == "reasoning-high"
    assert sel.selected_runtime == "claude-code"
    # Both the original preferred and the fallback chain land on candidates.
    models = [c.model for c in sel.candidates]
    assert "openai/gpt-4o" in models
    assert any(m.startswith("claude/") for m in models)


# ── skills ───────────────────────────────────────────────────────────────────


def test_skills_record_all_outcomes(clean_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True})
    manifest = _manifest(
        skills=[
            "summarize",  # builtin (no candidates in SKILL_MAP)
            "custom-skill",  # passthrough (not in SKILL_MAP)
            "web-search",  # missing — no brave/serper/tavily on PATH
        ]
    )
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    by_skill = {s.skill: s for s in plan.trace.skills}
    assert by_skill["summarize"].outcome == "builtin"
    assert by_skill["summarize"].resolved_to is None

    assert by_skill["custom-skill"].outcome == "passthrough"
    assert by_skill["custom-skill"].resolved_to == "custom-skill"

    assert by_skill["web-search"].outcome == "missing"
    assert by_skill["web-search"].candidates == [
        "brave-mcp",
        "serper-mcp",
        "tavily-mcp",
    ]


def test_skills_record_resolved_with_chosen_tool(clean_env, monkeypatch):
    """`code-execution` resolves to `bash` because /bin/bash is on PATH in the
    test environment. Asserts the resolver picked the first candidate that
    shutil.which() found, and the trace records both the choice and the pool."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True})
    manifest = _manifest(skills=["code-execution"])
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    skill = plan.trace.skills[0]
    assert skill.skill == "code-execution"
    assert skill.outcome == "resolved"
    assert skill.resolved_to == "bash"
    assert "bash" in skill.candidates


# ── mcp_tools ────────────────────────────────────────────────────────────────


def test_mcp_tools_recorded_as_registered(clean_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    table = _runtimes(**{"claude-code": True})
    manifest = _manifest(tools=ToolsSpec(mcp=["github-mcp", "brave-mcp"]))
    with patch("agentspec.resolver.resolver._detect_runtimes", return_value=table):
        plan = resolve(manifest)

    names = [m.name for m in plan.trace.mcp_tools]
    assert names == ["github-mcp", "brave-mcp"]
    for entry in plan.trace.mcp_tools:
        assert entry.outcome == "registered"


# ── trace shape contract ─────────────────────────────────────────────────────


def test_trace_serialises_with_extra_forbid(clean_env, monkeypatch):
    """``extra=forbid`` on every trace model — typos can't silently corrupt
    a record. Mirrors the ExecutionRecord convention."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResolverTrace(unknown_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ModelSelection(typo=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SkillResolution(skill="x", outcome="resolved", typo=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        McpToolResolution(name="x", typo=1)  # type: ignore[call-arg]
