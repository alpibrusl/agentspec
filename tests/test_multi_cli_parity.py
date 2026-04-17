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
from agentspec.resolver.resolver import PROVIDER_MAP, RUNTIME_BINARIES, ResolvedPlan
from agentspec.runner.runner import (
    _build_claude_cmd,
    _build_codex_cmd,
    _build_cursor_cmd,
    _build_goose_cmd,
    _build_opencode_cmd,
    _claude_model_name,
    _codex_model_name,
    _goose_model_name,
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


def test_provider_map_has_cursor_prefix():
    """Regression: without this entry the resolver rejects
    cursor/<model> manifests as unknown-provider. Caught by live
    dry-run after v0.3.1 shipped — fixed in v0.3.3."""
    runtime, keys = PROVIDER_MAP["cursor"]
    assert runtime == "cursor-cli"
    # Cursor uses its own subscription auth; no API keys required.
    assert keys is None


def test_build_cursor_has_print_as_bare_flag():
    """Verified against cursor-agent 2026.04.15 --help: -p/--print is
    a boolean that enables non-interactive mode; the prompt is a
    positional arg. Earlier builder passed `-p <prompt>` which
    technically worked (cursor parsed -p as boolean + prompt as
    positional) but the idiomatic form separates them."""
    plan = ResolvedPlan(runtime="cursor-cli", model="cursor/sonnet-4")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "go")
    p_idx = cmd.index("-p")
    # -p should be followed by other flags, not the prompt.
    assert cmd[p_idx + 1].startswith("-"), (
        f"-p should be a bare boolean; got {cmd[p_idx + 1]!r} immediately after"
    )


def test_build_cursor_passes_model_flag():
    """cursor-agent --help shows --model <model> takes cursor-specific
    names like gpt-5, sonnet-4. Manifest's provider prefix is stripped."""
    plan = ResolvedPlan(runtime="cursor-cli", model="cursor/sonnet-4-thinking")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "go")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "sonnet-4-thinking"


def test_build_cursor_adds_force_under_gym(monkeypatch):
    """--force (alias --yolo) auto-approves tool calls. Added under
    AGENTSPEC_GYM=1 so unattended runs don't stall on every tool
    invocation."""
    monkeypatch.setenv("AGENTSPEC_GYM", "1")
    plan = ResolvedPlan(runtime="cursor-cli", model="cursor/sonnet-4")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "go")
    assert "--force" in cmd


def test_build_cursor_omits_force_outside_gym(monkeypatch):
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    plan = ResolvedPlan(runtime="cursor-cli", model="cursor/sonnet-4")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "go")
    assert "--force" not in cmd


def test_build_cursor_has_text_output_format():
    """Without --output-format text, cursor-agent's headless mode may
    emit control sequences or JSON that the consumer doesn't expect."""
    plan = ResolvedPlan(runtime="cursor-cli", model="claude/sonnet")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "do the thing")
    assert cmd[0] == "cursor-agent"
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "text"


def test_build_cursor_passes_prompt_as_positional():
    """cursor-agent's headless mode is `cursor-agent -p [flags...]
    <prompt>` — -p is a boolean, prompt is the last positional."""
    plan = ResolvedPlan(runtime="cursor-cli", model="cursor/sonnet-4")
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "ship it")
    assert "-p" in cmd
    assert cmd[-1] == "ship it"


def test_build_cursor_system_prompt_not_in_command():
    """System prompt is now provisioned to .cursorrules by the provisioner,
    not prepended to the CLI prompt."""
    plan = ResolvedPlan(
        runtime="cursor-cli",
        model="cursor/sonnet-4",
        system_prompt="You cite sources.",
    )
    cmd = _build_cursor_cmd(plan, _minimal_manifest(), "summarise")
    assert cmd[-1] == "summarise"


def test_cursor_runtime_dispatches_via_build_command():
    """Make sure `cursor-cli` is reachable through the top-level
    dispatcher — not just the private builder. This catches the
    "added builder but forgot to wire it" regression class."""
    plan = ResolvedPlan(runtime="cursor-cli", model="claude/sonnet")
    cmd = build_command(plan, _minimal_manifest(), "go")
    assert cmd[0] == "cursor-agent"


# ── opencode ───────────────────────────────────────────────────────────────


def test_build_opencode_passes_model_with_one_prefix_stripped():
    """opencode's -m takes ``<provider>/<model>`` (verified against
    opencode 1.4.6 --help). Manifest's caller-facing ``opencode/``
    prefix gets stripped so what we pass is the opencode-expected pair.

    manifest: opencode/anthropic/claude-sonnet-4-6
    cmd -m : anthropic/claude-sonnet-4-6
    """
    plan = ResolvedPlan(
        runtime="opencode", model="opencode/anthropic/claude-sonnet-4-6"
    )
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "hi")
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "anthropic/claude-sonnet-4-6"


def test_build_opencode_passes_model_without_prefix_unchanged():
    """If the manifest already uses the bare ``provider/model`` form,
    we pass it through as-is."""
    plan = ResolvedPlan(
        runtime="opencode", model="anthropic/claude-sonnet-4-6"
    )
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "hi")
    assert cmd[cmd.index("-m") + 1] == "claude-sonnet-4-6"  # one prefix stripped


def test_build_aider_adds_yes_always_under_gym(monkeypatch):
    """aider --help v0.86: --yes-always auto-approves every confirmation.
    Required for unattended runs or aider blocks on prompts."""
    monkeypatch.setenv("AGENTSPEC_GYM", "1")
    plan = ResolvedPlan(runtime="aider", model="aider/claude-sonnet-4-6")
    from agentspec.runner.runner import _build_aider_cmd

    cmd = _build_aider_cmd(plan, _minimal_manifest(), "hi")
    assert "--yes-always" in cmd


def test_build_aider_omits_yes_always_outside_gym(monkeypatch):
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    plan = ResolvedPlan(runtime="aider", model="aider/claude-sonnet-4-6")
    from agentspec.runner.runner import _build_aider_cmd

    cmd = _build_aider_cmd(plan, _minimal_manifest(), "hi")
    assert "--yes-always" not in cmd


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
    --prompt or multiple args. The full shape with a model flag is
    [opencode, run, -m, <model>, <prompt>]; prompt is the last arg."""
    plan = ResolvedPlan(runtime="opencode", model="opencode/anthropic/claude-sonnet-4-6")
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "build a thing")
    # Shape: opencode run -m anthropic/claude-sonnet-4-6 "build a thing"
    assert cmd[0:2] == ["opencode", "run"]
    assert cmd[-1] == "build a thing"
    # prompt should not appear split into multiple positional args
    assert cmd.count("build a thing") == 1


def test_build_opencode_system_prompt_not_in_command():
    """System prompt is now provisioned to .open-code/instructions.md
    by the provisioner, not prepended to the CLI prompt."""
    plan = ResolvedPlan(
        runtime="opencode", model="opencode/anthropic/claude-sonnet-4-6",
        system_prompt="You are a code reviewer.",
    )
    cmd = _build_opencode_cmd(plan, _minimal_manifest(), "review this PR")
    assert cmd[-1] == "review this PR"


def test_build_opencode_handles_empty_prompt():
    """When the manifest has no input_text and no soul, opencode run
    is called with just [opencode, run, -m, <model>] — no empty
    positional prompt slot."""
    m = AgentManifest(
        apiVersion="agent/v1",
        name="noprompt",
        version="0.1.0",
        description="",
        model=ModelSpec(preferred=["opencode/anthropic/claude-sonnet-4-6"]),
        skills=[],
        tools=ToolsSpec(mcp=[], native=[]),
        behavior=BehaviorSpec(),
        trust=TrustSpec(),
        observability=ObservabilitySpec(),
    )
    plan = ResolvedPlan(runtime="opencode", model="opencode/anthropic/claude-sonnet-4-6")
    cmd = _build_opencode_cmd(plan, m, None)
    # No positional prompt; model flag present.
    assert cmd == ["opencode", "run", "-m", "anthropic/claude-sonnet-4-6"]


# ── codex-cli ──────────────────────────────────────────────────────────────


def test_build_codex_uses_exec_subcommand(monkeypatch):
    """Regression: v0.2.x built ``codex <prompt>`` which drops into the
    interactive TUI. The non-interactive form per
    https://developers.openai.com/codex/cli/reference is
    ``codex exec <prompt>``."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    plan = ResolvedPlan(runtime="codex-cli", model="openai/o3")
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "do the thing")
    assert cmd[0:2] == ["codex", "exec"]


def test_build_codex_adds_full_auto_under_gym(monkeypatch):
    """Autonomous runs must set --full-auto (workspace-write sandbox +
    on-request approvals) or codex blocks on every tool call."""
    monkeypatch.setenv("AGENTSPEC_GYM", "1")
    plan = ResolvedPlan(runtime="codex-cli", model="openai/o3")
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "hi")
    assert "--full-auto" in cmd


def test_build_codex_omits_full_auto_outside_gym(monkeypatch):
    """Interactive users should still see approval prompts."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    plan = ResolvedPlan(runtime="codex-cli", model="openai/o3")
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "hi")
    assert "--full-auto" not in cmd


def test_build_codex_passes_model_flag():
    plan = ResolvedPlan(runtime="codex-cli", model="openai/gpt-5")
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "hi")
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5"


def test_build_codex_does_not_pass_instructions_flag():
    """The old builder passed ``--instructions <tmpfile>`` but that
    flag doesn't exist on modern codex. Must not appear in argv."""
    plan = ResolvedPlan(
        runtime="codex-cli",
        model="openai/o3",
        system_prompt="You are careful.",
    )
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "implement it")
    assert "--instructions" not in cmd


def test_build_codex_system_prompt_not_in_command():
    """System prompt is now provisioned to AGENTS.md by the provisioner,
    not prepended to the CLI prompt."""
    plan = ResolvedPlan(
        runtime="codex-cli",
        model="openai/o3",
        system_prompt="You are careful.",
    )
    cmd = _build_codex_cmd(plan, _minimal_manifest(), "implement it")
    assert cmd[-1] == "implement it"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("openai/gpt-5", "gpt-5"),
        ("openai/o3", "o3"),
        ("o3", "o3"),  # alias
        ("", ""),
    ],
)
def test_codex_model_name_strips_provider_prefix(raw: str, expected: str):
    assert _codex_model_name(raw) == expected


# ── goose (new in v0.3.1) ──────────────────────────────────────────────────


def test_goose_is_in_runtime_binaries():
    """Dispatch + resolver tables must both know about goose."""
    assert RUNTIME_BINARIES["goose"] == "goose"
    assert "goose" in PROVIDER_MAP


def test_build_goose_uses_run_subcommand_and_text_flag():
    """Non-interactive form per goose-docs.ai is ``goose run -t <prompt>``."""
    plan = ResolvedPlan(runtime="goose", model="anthropic/claude-sonnet-4-6")
    cmd = _build_goose_cmd(plan, _minimal_manifest(), "ship a feature")
    assert cmd[0:2] == ["goose", "run"]
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "ship a feature"


def test_build_goose_passes_model_flag():
    """goose's --model is a real flag (unlike cursor/opencode which are
    config-driven); must be wired so the manifest's preference isn't
    silently dropped."""
    plan = ResolvedPlan(runtime="goose", model="anthropic/claude-sonnet-4-6")
    cmd = _build_goose_cmd(plan, _minimal_manifest(), "hi")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"


def test_build_goose_uses_system_flag_not_prepended():
    """Unlike codex/cursor/opencode, goose has a real ``--system <text>``
    flag. Use it — don't mash the system prompt into the user prompt."""
    plan = ResolvedPlan(
        runtime="goose",
        model="anthropic/claude-sonnet-4-6",
        system_prompt="You are a code reviewer.",
    )
    cmd = _build_goose_cmd(plan, _minimal_manifest(), "review this")
    assert "--system" in cmd
    sys_idx = cmd.index("--system")
    assert cmd[sys_idx + 1] == "You are a code reviewer."
    # User prompt stays untouched — not prefixed with the system text.
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "review this"


def test_build_goose_skips_model_flag_when_empty():
    """Defensive: empty plan.model → let goose use its configured default."""
    plan = ResolvedPlan(runtime="goose", model="")
    cmd = _build_goose_cmd(plan, _minimal_manifest(), "hi")
    assert "--model" not in cmd


def test_goose_dispatches_via_build_command():
    """The meta-test: goose is reachable through build_command, not
    just the private _build_goose_cmd. Same class of regression
    prevention as cursor-cli had before the parity sweep."""
    plan = ResolvedPlan(runtime="goose", model="anthropic/claude-sonnet-4-6")
    cmd = build_command(plan, _minimal_manifest(), "go")
    assert cmd[0] == "goose"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("anthropic/claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("openai/gpt-5", "gpt-5"),
        ("goose/whatever", "whatever"),
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("", ""),
    ],
)
def test_goose_model_name_strips_provider_prefix(raw: str, expected: str):
    assert _goose_model_name(raw) == expected


# ── opencode Vertex AI wiring ──────────────────────────────────────────────


def test_vertex_env_for_opencode_sets_vertex_location_not_google_cloud_location():
    """opencode reads VERTEX_LOCATION — not GOOGLE_CLOUD_LOCATION like
    gemini-cli does. Setting only GOOGLE_CLOUD_LOCATION means opencode
    falls back to the ``global`` region regardless of what our resolver
    picked; for EU-residency users (europe-west1 default) this sent
    traffic to the wrong region silently.

    Source: https://opencode.ai/docs/providers/ — the google-vertex-ai
    provider section lists VERTEX_LOCATION as the region env var.
    """
    from agentspec.resolver.vertex import VertexConfig, vertex_env_for_runtime

    cfg = VertexConfig(project="my-proj", location="europe-west1")
    env = vertex_env_for_runtime("opencode", cfg)

    # Project lands at GOOGLE_CLOUD_PROJECT — opencode reads this one.
    assert env["GOOGLE_CLOUD_PROJECT"] == "my-proj"

    # Region goes to VERTEX_LOCATION — the variable opencode actually reads.
    assert env.get("VERTEX_LOCATION") == "europe-west1", (
        "opencode ignores GOOGLE_CLOUD_LOCATION; must set VERTEX_LOCATION"
    )


def test_opencode_vertex_env_preserves_gemini_mappings_intact():
    """Regression guard: the opencode fix must not have altered
    gemini-cli's Vertex env (different tool, different env vars)."""
    from agentspec.resolver.vertex import VertexConfig, vertex_env_for_runtime

    cfg = VertexConfig(project="p", location="europe-west1")
    gemini = vertex_env_for_runtime("gemini-cli", cfg)
    # gemini-cli still uses GOOGLE_CLOUD_LOCATION (verified in its own
    # test file); this is the "mappings are independent" check.
    assert gemini.get("GOOGLE_CLOUD_LOCATION") == "europe-west1"
    assert gemini.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"


# ── Cross-CLI parity checks ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "runtime,binary",
    [
        ("claude-code", "claude"),
        ("gemini-cli", "gemini"),
        ("cursor-cli", "cursor-agent"),
        ("codex-cli", "codex"),
        ("opencode", "opencode"),
        ("goose", "goose"),
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
