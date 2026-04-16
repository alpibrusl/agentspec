"""Parity audit for claude-code, cursor-cli, and opencode runners.

The gemini-cli field report exposed that the runner builders had drifted
from the real CLI flags — wrong env vars, missing model selection, wrong
subcommand names. This file pins the corrected shape for each of the
other three currently-supported CLIs so the same regressions can't
recur silently.

Each CLI was cross-checked against (a) its official docs and (b)
caloron-noether's field-validated FRAMEWORKS table where the agent has
actually been run in production. Anything that differs between the
spec and the runner would have been a silent breakage class.
"""

from __future__ import annotations

import pytest

from agentspec.parser.manifest import (
    AgentManifest,
    BehaviorSpec,
    ModelSpec,
    ObservabilitySpec,
    ToolsSpec,
    TrustSpec,
)
from agentspec.resolver.resolver import RUNTIME_BINARIES, ResolvedPlan
from agentspec.runner.runner import (
    _build_claude_cmd,
    _build_cursor_cmd,
    _build_opencode_cmd,
    _claude_model_name,
    build_command,
)


def _minimal_manifest(model_preferred: str = "claude/claude-sonnet-4-6") -> AgentManifest:
    return AgentManifest(
        apiVersion="agent/v1",
        name="test-agent",
        version="0.1.0",
        description="test",
        model=ModelSpec(preferred=[model_preferred]),
        skills=[],
        tools=ToolsSpec(mcp=[], native=[]),
        behavior=BehaviorSpec(),
        trust=TrustSpec(),
        observability=ObservabilitySpec(),
    )


# ── claude-code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("claude/claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("anthropic/claude-opus-4-6", "claude-opus-4-6"),
        ("sonnet", "sonnet"),  # alias — already bare
        ("claude-haiku-4-5", "claude-haiku-4-5"),
        ("", ""),
    ],
)
def test_claude_model_name_strips_provider_prefix(raw: str, expected: str):
    assert _claude_model_name(raw) == expected


def test_build_claude_passes_model_flag(monkeypatch):
    """Regression: `--model <name>` must be in argv or claude picks its
    own default regardless of manifest.model.preferred."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    plan = ResolvedPlan(
        runtime="claude-code", model="claude/claude-sonnet-4-6"
    )
    cmd = _build_claude_cmd(plan, _minimal_manifest(), "hi")
    assert "--model" in cmd
    i = cmd.index("--model")
    assert cmd[i + 1] == "claude-sonnet-4-6"


def test_build_claude_accepts_model_alias():
    plan = ResolvedPlan(runtime="claude-code", model="sonnet")
    cmd = _build_claude_cmd(plan, _minimal_manifest(), "hi")
    assert "--model" in cmd
    i = cmd.index("--model")
    assert cmd[i + 1] == "sonnet"


def test_build_claude_keeps_existing_flags(monkeypatch):
    """Check the flags we had before the model addition still make it
    through — --dangerously-skip-permissions, --system-prompt, -p."""
    monkeypatch.setenv("AGENTSPEC_GYM", "1")
    plan = ResolvedPlan(
        runtime="claude-code",
        model="claude/claude-sonnet-4-6",
        system_prompt="You are careful.",
    )
    cmd = _build_claude_cmd(plan, _minimal_manifest(), "build a thing")
    assert "--dangerously-skip-permissions" in cmd
    assert "--system-prompt" in cmd
    sp_i = cmd.index("--system-prompt")
    assert cmd[sp_i + 1] == "You are careful."
    assert "-p" in cmd
    p_i = cmd.index("-p")
    assert cmd[p_i + 1] == "build a thing"


def test_build_claude_skips_model_when_plan_empty():
    """Defensive: no plan.model → no --model flag (let claude use its
    configured default rather than passing an empty string)."""
    plan = ResolvedPlan(runtime="claude-code", model="")
    cmd = _build_claude_cmd(plan, _minimal_manifest(), "hi")
    assert "--model" not in cmd


# ── cursor-cli ─────────────────────────────────────────────────────────────


def test_runtime_binaries_cursor_points_at_cursor_agent():
    """The cursor CLI binary is `cursor-agent`, not `cursor`. Previously
    the resolver looked for `cursor` on PATH and missed every real
    install. Also the runtime key is now `cursor-cli` to match caloron-
    noether's naming and every other `-cli` entry in the table."""
    assert RUNTIME_BINARIES.get("cursor-cli") == "cursor-agent"
    assert "cursor" not in RUNTIME_BINARIES  # old name purged


def test_build_cursor_has_text_output_format():
    """Without --output-format text, cursor-agent's headless mode may
    emit control sequences or JSON that the consumer doesn't expect."""
    plan = ResolvedPlan(runtime="cursor-cli", model="claude/sonnet")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "do the thing")
    assert cmd[0] == "cursor-agent"
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "text"


def test_build_cursor_uses_p_for_non_interactive_prompt():
    """cursor-agent's headless mode is `cursor-agent -p <prompt>`.
    Without -p it drops into interactive mode and hangs the subprocess."""
    plan = ResolvedPlan(runtime="cursor-cli", model="claude/sonnet")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "ship it")
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "ship it"


def test_build_cursor_prepends_system_prompt():
    """cursor-agent has no dedicated --system-prompt on headless mode,
    so we prepend it to the user prompt with a blank-line separator."""
    plan = ResolvedPlan(
        runtime="cursor-cli",
        model="claude/sonnet",
        system_prompt="You cite sources.",
    )
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "summarise")
    idx = cmd.index("-p")
    combined = cmd[idx + 1]
    assert combined.startswith("You cite sources.")
    assert "summarise" in combined


def test_cursor_runtime_dispatches_via_build_command():
    """Make sure `cursor-cli` is reachable through the top-level
    dispatcher — not just the private builder. This catches the
    "added builder but forgot to wire it" regression class."""
    plan = ResolvedPlan(runtime="cursor-cli", model="claude/sonnet")
    cmd = build_command(plan, _minimal_manifest(), "go")
    assert cmd[0] == "cursor-agent"


# ── opencode ───────────────────────────────────────────────────────────────


def test_build_opencode_uses_run_subcommand():
    """The non-interactive form per https://opencode.ai/docs/cli/ is
    ``opencode run <prompt>``. The previous --print form produced the
    wrong error message on modern opencode (``unknown flag``)."""
    plan = ResolvedPlan(
        runtime="opencode", model="opencode/default",
        system_prompt="Be concise.",
    )
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "hello")
    assert cmd[0:2] == ["opencode", "run"]


def test_build_opencode_prompt_is_single_positional():
    """opencode run takes one positional prompt arg — not split across
    --prompt or multiple args."""
    plan = ResolvedPlan(runtime="opencode", model="opencode/default")
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "build a thing")
    # cmd = ["opencode", "run", "build a thing"]
    assert len(cmd) == 3
    assert cmd[2] == "build a thing"


def test_build_opencode_prepends_system_prompt():
    """No --system-prompt flag on `opencode run`, so we prepend."""
    plan = ResolvedPlan(
        runtime="opencode", model="opencode/default",
        system_prompt="You are a code reviewer.",
    )
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "review this PR")
    combined = cmd[2]
    assert "You are a code reviewer." in combined
    assert "review this PR" in combined
    # System prompt appears first with a blank line before user prompt
    assert combined.index("You are") < combined.index("review this PR")


def test_build_opencode_handles_empty_prompt():
    """When the manifest has no input_text and no soul, opencode run
    is called with no positional prompt (empty string would break)."""
    m = AgentManifest(
        apiVersion="agent/v1",
        name="noprompt",
        version="0.1.0",
        description="",
        model=ModelSpec(preferred=["opencode/default"]),
        skills=[],
        tools=ToolsSpec(mcp=[], native=[]),
        behavior=BehaviorSpec(),
        trust=TrustSpec(),
        observability=ObservabilitySpec(),
    )
    plan = ResolvedPlan(runtime="opencode", model="opencode/default")
    cmd = _build_opencode_cmd(plan, m, None)
    assert cmd == ["opencode", "run"]


# ── Cross-CLI parity checks ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "runtime,binary",
    [
        ("claude-code", "claude"),
        ("gemini-cli", "gemini"),
        ("cursor-cli", "cursor-agent"),
        ("codex-cli", "codex"),
        ("opencode", "opencode"),
        ("aider", "aider"),
        ("ollama", "ollama"),
    ],
)
def test_runtime_binaries_table_matches_published_cli_names(
    runtime: str, binary: str
):
    """One row per supported CLI. If a binary name changes upstream,
    this test fires before users hit a silent 'command not found'."""
    assert RUNTIME_BINARIES[runtime] == binary


def test_all_registered_runtimes_have_a_builder():
    """Every runtime in RUNTIME_BINARIES must have a builder in the
    dispatcher. Otherwise build_command raises NotImplementedError at
    runtime — the bug cursor-cli had before this commit."""
    # Using a phony plan for each — we only want to confirm dispatch
    # doesn't raise NotImplementedError. The actual argv content is
    # tested elsewhere.
    for runtime in RUNTIME_BINARIES:
        plan = ResolvedPlan(runtime=runtime, model="")
        try:
            build_command(plan, _minimal_manifest(), "probe")
        except NotImplementedError as exc:
            pytest.fail(
                f"{runtime} is in RUNTIME_BINARIES but has no builder: {exc}"
            )
        except Exception:
            # Other exceptions (e.g. missing manifest fields) are fine —
            # we're only guarding against "no dispatch entry".
            pass
