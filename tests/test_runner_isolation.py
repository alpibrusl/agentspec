"""Runner integration tests for bubblewrap-backed isolation.

Uses monkeypatched ``shutil.which`` and ``subprocess.run`` to verify
that the chosen backend translates into the expected process
invocation — no real bwrap, no real runtime CLI.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from pathlib import Path

import pytest

from agentspec.parser.manifest import AgentManifest, TrustSpec
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner


@pytest.fixture
def fake_provision(monkeypatch):
    monkeypatch.setattr(runner, "provision", lambda plan, manifest, workdir: None)


@pytest.fixture
def fake_run(monkeypatch):
    """Capture argv passed to subprocess.run and return exit 0."""
    calls: list[dict] = []

    def _fake(cmd, env=None, cwd=None, **kwargs):
        calls.append({"cmd": cmd, "env": env, "cwd": cwd})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", _fake)
    return calls


def _plan() -> ResolvedPlan:
    return ResolvedPlan(
        runtime="claude-code",
        model="claude/claude-sonnet-4-6",
        tools=[],
        auth_source="env.ANTHROPIC_API_KEY",
        system_prompt="",
        warnings=[],
        decisions=[],
    )


def _manifest(trust: TrustSpec | None = None) -> AgentManifest:
    return AgentManifest(
        name="iso-test",
        version="0.1.0",
        runtime="claude-code",
        trust=trust or TrustSpec(filesystem="full", network="allowed", exec="full"),
    )


# ── Backend selection via execute() ───────────────────────────────────────────


def test_execute_auto_wraps_in_bwrap_when_available(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap" if name == "bwrap" else None)

    runner.execute(_plan(), _manifest(), workdir=tmp_path, emit_record=False)

    argv = fake_run[0]["cmd"]
    assert argv[0] == "/bin/bwrap"
    assert "--unshare-all" in argv
    # The original command is after --
    assert argv[argv.index("--") + 1] == "claude"


def test_execute_auto_without_bwrap_and_permissive_trust_runs_raw(
    tmp_path, fake_provision, fake_run, monkeypatch, caplog
):
    monkeypatch.setattr("shutil.which", lambda name: None)
    caplog.set_level(logging.WARNING, logger="agentspec.runner.runner")

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="full", network="allowed", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    assert argv[0] == "claude"  # unwrapped

    # Assert the warning was actually logged — PR #17 review called out
    # that the previous version had a "A warning was surfaced somewhere"
    # comment but no assertion.
    assert any(
        "unsandboxed" in r.message.lower() or "no isolation" in r.message.lower()
        for r in caplog.records
    ), f"expected an unsandboxed/no-isolation warning; got {[r.message for r in caplog.records]}"


def test_execute_auto_without_bwrap_and_tight_trust_raises(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: None)
    tight = _manifest(TrustSpec(filesystem="none"))

    with pytest.raises(RuntimeError, match="bubblewrap"):
        runner.execute(_plan(), tight, workdir=tmp_path, emit_record=False)

    assert fake_run == []  # subprocess never invoked


def test_execute_via_bwrap_explicit_wraps(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    runner.execute(
        _plan(), _manifest(), workdir=tmp_path, emit_record=False, via="bwrap"
    )

    assert fake_run[0]["cmd"][0] == "/bin/bwrap"


def test_execute_via_bwrap_missing_raises(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="bwrap"):
        runner.execute(
            _plan(), _manifest(), workdir=tmp_path, emit_record=False, via="bwrap"
        )


def test_execute_via_none_with_permissive_trust_skips_sandbox(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="full", network="allowed", exec="full")),
        workdir=tmp_path,
        emit_record=False,
        via="none",
    )

    assert fake_run[0]["cmd"][0] == "claude"  # not wrapped


def test_execute_via_none_with_tight_trust_requires_unsafe_flag(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    tight = _manifest(TrustSpec(filesystem="none"))

    with pytest.raises(RuntimeError, match="unsafe"):
        runner.execute(
            _plan(), tight, workdir=tmp_path, emit_record=False, via="none"
        )


def test_execute_via_none_with_tight_trust_and_unsafe_flag_allowed(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    tight = _manifest(TrustSpec(filesystem="none"))

    runner.execute(
        _plan(),
        tight,
        workdir=tmp_path,
        emit_record=False,
        via="none",
        unsafe_no_isolation=True,
    )

    assert fake_run[0]["cmd"][0] == "claude"


# ── Record co-existence ───────────────────────────────────────────────────────


def test_record_still_written_under_bwrap_path(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    from agentspec.records.manager import RecordManager

    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    runner.execute(_plan(), _manifest(), workdir=tmp_path)

    records = RecordManager(tmp_path).list()
    assert len(records) == 1


def test_record_captures_isolation_backend_used(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    """Record's warnings (or a future isolation field) should surface which
    backend ran. For now we assert the warning list reflects unsandboxed runs."""
    from agentspec.records.manager import RecordManager

    monkeypatch.setattr("shutil.which", lambda name: None)
    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="full", network="allowed", exec="full")),
        workdir=tmp_path,
    )

    r = RecordManager(tmp_path).list()[0]
    # Warning about running unsandboxed should have been carried through.
    assert any("unsandboxed" in w.lower() or "no isolation" in w.lower() for w in r.warnings)


# ── Regressions for PR #17 review ─────────────────────────────────────────────


def test_execute_does_not_mutate_plan_warnings(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    """PR #17 review: warnings emitted by backend selection were being
    written back onto ``plan.warnings`` in-place, so reusing a plan
    (tests, future retry paths) accumulated stale warnings across runs."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    plan = _plan()
    plan.warnings = []  # start empty; seed known baseline
    original = list(plan.warnings)

    runner.execute(
        plan,
        _manifest(TrustSpec(filesystem="full", network="allowed", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    assert plan.warnings == original, (
        f"plan.warnings mutated: {plan.warnings!r} (baseline {original!r})"
    )


def test_vertex_auth_propagates_routing_vars_into_sandbox(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    """PR #17 review ship-blocker: when auth_source is Vertex AI, the
    Vertex routing env vars must be on the sandbox env allowlist **and**
    sourced from the enriched env dict (build_env overlays them). Without
    both, ``--clearenv`` wipes them and the sandboxed runtime fails
    auth inside the sandbox."""
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    # Stand in for build_env's layering — simulate that Vertex routing
    # landed in the subprocess env dict the runner will pass down.
    def _fake_build_env(plan):
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/u",
            "CLAUDE_CODE_USE_VERTEX": "1",
            "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
            "VERTEX_PROJECT": "my-project",
            "VERTEX_LOCATION": "us-central1",
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "CLOUD_ML_REGION": "us-central1",
        }

    monkeypatch.setattr(runner, "build_env", _fake_build_env)

    vertex_plan = ResolvedPlan(
        runtime="claude-code",
        model="claude/claude-sonnet-4-6",
        tools=[],
        auth_source="vertex-ai",
        system_prompt="",
        warnings=[],
        decisions=[],
    )
    runner.execute(vertex_plan, _manifest(), workdir=tmp_path, emit_record=False)

    argv = fake_run[0]["cmd"]
    # Collect --setenv triples.
    triples: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--setenv" and i + 2 < len(argv):
            triples[argv[i + 1]] = argv[i + 2]
            i += 3
        else:
            i += 1

    assert triples.get("CLAUDE_CODE_USE_VERTEX") == "1"
    assert triples.get("ANTHROPIC_VERTEX_PROJECT_ID") == "my-project"
    assert triples.get("VERTEX_PROJECT") == "my-project"
    assert triples.get("VERTEX_LOCATION") == "us-central1"
    assert triples.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"
