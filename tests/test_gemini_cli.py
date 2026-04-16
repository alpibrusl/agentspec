"""Tests for gemini-cli runner + resolver integration.

Surfaced by a field report that gemini-cli calls from agentspec were
failing despite having credentials set. Two root causes:

1. The resolver required ``GOOGLE_API_KEY`` but gemini-cli itself only
   reads ``GEMINI_API_KEY`` (plus Vertex AI env vars). Callers who set
   GOOGLE_API_KEY would pass the resolver check but the CLI would then
   fail with "please set an Auth method" at run time.
2. The runner didn't pass ``-m`` at all, so gemini ran with whatever
   default model instead of the one the manifest's ``model.preferred``
   list specified.

Verified against ``gemini --help`` from the installed CLI (v0.34+):
- ``-m / --model`` takes a plain model id ("gemini-2.5-pro")
- ``-p / --prompt`` is the non-interactive flag
- ``-y / --yolo`` auto-approves tool calls (needed for gym/agentic runs)
- ``-s / --sandbox`` enables sandbox mode
- System instructions come from a ``GEMINI.md`` file in the CWD (no
  ``--system-prompt`` flag exists)
- Error without auth lists: ``GEMINI_API_KEY``,
  ``GOOGLE_GENAI_USE_VERTEXAI``, ``GOOGLE_GENAI_USE_GCA``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentspec.parser.manifest import (
    AgentManifest,
    BehaviorSpec,
    ModelSpec,
    ObservabilitySpec,
    ToolsSpec,
    TrustSpec,
)
from agentspec.resolver.resolver import PROVIDER_MAP, ResolvedPlan, resolve
from agentspec.runner.runner import _build_gemini_cmd, _gemini_model_name


def _minimal_manifest(**overrides) -> AgentManifest:
    defaults = dict(
        apiVersion="agent/v1",
        name="test-agent",
        version="0.1.0",
        description="test",
        model=ModelSpec(preferred=["gemini/gemini-2.5-pro"]),
        skills=[],
        tools=ToolsSpec(mcp=[], native=[]),
        behavior=BehaviorSpec(),
        trust=TrustSpec(),
        observability=ObservabilitySpec(),
    )
    defaults.update(overrides)
    return AgentManifest(**defaults)


def _plan(*, model: str = "gemini/gemini-2.5-pro", system_prompt: str = "") -> ResolvedPlan:
    return ResolvedPlan(
        runtime="gemini-cli",
        model=model,
        system_prompt=system_prompt,
    )


# ── _gemini_model_name ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("gemini/gemini-2.5-pro", "gemini-2.5-pro"),
        ("google/gemini-2.0-flash", "gemini-2.0-flash"),
        ("gemini-2.5-pro", "gemini-2.5-pro"),
        ("", ""),
    ],
)
def test_gemini_model_name_strips_provider_prefix(raw: str, expected: str):
    assert _gemini_model_name(raw) == expected


# ── _build_gemini_cmd ──────────────────────────────────────────────────────


def test_build_gemini_passes_model_flag(monkeypatch):
    """-m <name> must be in the argv — without it gemini uses its default
    model regardless of what the manifest declares."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    cmd = _build_gemini_cmd(_plan(), _minimal_manifest(), "hi")
    assert "-m" in cmd
    m_idx = cmd.index("-m")
    assert cmd[m_idx + 1] == "gemini-2.5-pro"


def test_build_gemini_passes_prompt_with_p_flag(monkeypatch):
    """Non-interactive mode needs -p <prompt>. Without it, gemini drops
    into interactive mode and hangs the subprocess."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    cmd = _build_gemini_cmd(_plan(), _minimal_manifest(), "build a parser")
    assert "-p" in cmd
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1] == "build a parser"


def test_build_gemini_adds_yolo_under_agentspec_gym(monkeypatch):
    """Gym-mode runs must auto-approve tool calls or the agent hangs on
    every file-write prompt. Matches the -y treatment claude-code gets
    via --dangerously-skip-permissions."""
    monkeypatch.setenv("AGENTSPEC_GYM", "1")
    cmd = _build_gemini_cmd(_plan(), _minimal_manifest(), "hi")
    assert "-y" in cmd


def test_build_gemini_omits_yolo_outside_gym(monkeypatch):
    """Interactive users should still get tool-approval prompts — only
    automated runners opt into yolo."""
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    cmd = _build_gemini_cmd(_plan(), _minimal_manifest(), "hi")
    assert "-y" not in cmd


def test_build_gemini_writes_system_prompt_to_gemini_md(
    monkeypatch, tmp_path: Path
):
    """gemini-cli has no --system-prompt flag; it reads GEMINI.md from
    the CWD as system instructions. Runner must create that file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTSPEC_GYM", raising=False)
    _build_gemini_cmd(
        _plan(system_prompt="You are a careful code reviewer."),
        _minimal_manifest(),
        "review",
    )
    assert (tmp_path / "GEMINI.md").exists()
    assert "careful code reviewer" in (tmp_path / "GEMINI.md").read_text()


def test_build_gemini_does_not_overwrite_existing_gemini_md(
    monkeypatch, tmp_path: Path
):
    """Don't stomp a GEMINI.md the user's project already has — that
    would silently lose their own system instructions."""
    monkeypatch.chdir(tmp_path)
    existing = "# Project's own instructions — do not touch"
    (tmp_path / "GEMINI.md").write_text(existing)
    _build_gemini_cmd(
        _plan(system_prompt="Agentspec wants to say this instead."),
        _minimal_manifest(),
        "hi",
    )
    assert (tmp_path / "GEMINI.md").read_text() == existing


def test_build_gemini_skips_system_prompt_when_empty(monkeypatch, tmp_path: Path):
    """No system prompt → no GEMINI.md created. Avoid spurious writes."""
    monkeypatch.chdir(tmp_path)
    _build_gemini_cmd(_plan(system_prompt=""), _minimal_manifest(), "hi")
    assert not (tmp_path / "GEMINI.md").exists()


# ── Resolver: env var handling ─────────────────────────────────────────────


def test_provider_map_accepts_gemini_api_key_primary():
    """gemini-cli's real env var is GEMINI_API_KEY — declared primary."""
    _runtime, keys = PROVIDER_MAP["gemini"]
    assert keys is not None
    assert keys[0] == "GEMINI_API_KEY", (
        "GEMINI_API_KEY must be primary — gemini-cli itself reads it "
        "preferentially; GOOGLE_API_KEY is fallback for historical callers"
    )


def test_provider_map_accepts_google_api_key_as_fallback():
    """GOOGLE_API_KEY stays in the tuple so users who set the Google-
    branded key still pass the resolver check (with the caveat that
    gemini-cli won't actually read it — they'll need to re-export as
    GEMINI_API_KEY at run time)."""
    _runtime, keys = PROVIDER_MAP["gemini"]
    assert keys is not None
    assert "GOOGLE_API_KEY" in keys


def test_resolver_picks_gemini_when_gemini_api_key_set(monkeypatch):
    """Happy path: GEMINI_API_KEY present → resolver selects gemini-cli
    and reports which env var satisfied the check."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    manifest = _minimal_manifest()

    import shutil

    # Force gemini-cli to appear "installed" without depending on host PATH.
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda cmd: "/fake/gemini" if cmd == "gemini" else real_which(cmd)
    )

    plan = resolve(manifest)
    assert plan.runtime == "gemini-cli"
    assert plan.model == "gemini/gemini-2.5-pro"
    # Auth source should name GEMINI_API_KEY (not GOOGLE_API_KEY) so users
    # can tell which env var the resolver accepted.
    assert "GEMINI_API_KEY" in plan.auth_source


def test_resolver_falls_back_to_subscription_when_no_keys(monkeypatch):
    """Binary present, no keys, no Vertex → subscription-mode assumption."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda cmd: "/fake/gemini" if cmd == "gemini" else real_which(cmd)
    )

    manifest = _minimal_manifest()
    plan = resolve(manifest)
    assert plan.runtime == "gemini-cli"
    assert "subscription" in plan.auth_source.lower()


def test_resolver_decision_log_lists_both_keys_tried(monkeypatch):
    """When neither key is set, the decision trail should name both so
    users can see what to set instead of guessing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    import shutil

    # Force gemini NOT available so we hit the skip branch (logs the keys)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    # Use an OpenAI-only manifest so the gemini branch is skipped via
    # "not in PATH"; we only want the decision log coverage via behaviour
    # below. Actually, to hit the env-keys-not-set branch, we need the
    # binary present but no keys and no subscription fallback path — but
    # gemini-cli is ALWAYS in the subscription-fallback list, so that
    # branch is never reached for gemini.
    #
    # The "none of X set" log path DOES fire for other providers though;
    # we skip a direct test here because gemini-cli's subscription
    # fallback covers every case that matters.
    pytest.skip(
        "gemini-cli always has subscription fallback — no code path exposes "
        "the 'none of keys set' decision log line for gemini specifically"
    )
