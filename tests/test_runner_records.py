"""Integration tests: runner.execute() emits execution records.

Subprocess is monkeypatched so no real CLI is spawned — we assert the
record shape and contents, not actual runtime behaviour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.records.manager import RecordManager
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Replace subprocess.run with a controllable fake. Default: exit 0."""
    calls: list[dict] = []

    def _fake_run(cmd, env=None, cwd=None, **kwargs):
        calls.append({"cmd": cmd, "env": env, "cwd": cwd})
        return SimpleNamespace(returncode=_fake_run.returncode)

    _fake_run.returncode = 0
    monkeypatch.setattr(runner.subprocess, "run", _fake_run)
    return _fake_run


@pytest.fixture
def fake_provision(monkeypatch):
    """Skip the provisioner — it writes files that are irrelevant to these tests."""
    monkeypatch.setattr(runner, "provision", lambda plan, manifest, workdir: None)


def _manifest() -> AgentManifest:
    return AgentManifest(
        name="test-agent",
        version="0.1.0",
        runtime="claude-code",
    )


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


def test_execute_writes_record_by_default(tmp_path, fake_subprocess, fake_provision):
    exit_code = runner.execute(_plan(), _manifest(), workdir=tmp_path)
    assert exit_code == 0

    mgr = RecordManager(tmp_path)
    records = mgr.list()
    assert len(records) == 1


def test_record_carries_expected_fields(tmp_path, fake_subprocess, fake_provision):
    manifest = _manifest()
    runner.execute(_plan(), manifest, workdir=tmp_path)

    r = RecordManager(tmp_path).list()[0]
    assert r.manifest_hash == agent_hash(manifest)
    assert r.runtime == "claude-code"
    assert r.model == "claude/claude-sonnet-4-6"
    assert r.exit_code == 0
    assert r.outcome == "success"
    assert r.duration_s >= 0
    # ULID format — 26 chars.
    assert len(r.run_id) == 26


def test_record_outcome_failure_on_nonzero_exit(tmp_path, fake_subprocess, fake_provision):
    fake_subprocess.returncode = 17
    runner.execute(_plan(), _manifest(), workdir=tmp_path)

    r = RecordManager(tmp_path).list()[0]
    assert r.exit_code == 17
    assert r.outcome == "failure"


def test_emit_record_false_skips_writing(tmp_path, fake_subprocess, fake_provision):
    runner.execute(_plan(), _manifest(), workdir=tmp_path, emit_record=False)

    mgr = RecordManager(tmp_path)
    # Directory is created by the manager ctor; it should be empty.
    assert mgr.list() == []


def test_record_warnings_copied_from_plan(tmp_path, fake_subprocess, fake_provision):
    plan = _plan()
    plan.warnings = ["missing api key", "using fallback model"]
    runner.execute(plan, _manifest(), workdir=tmp_path)

    r = RecordManager(tmp_path).list()[0]
    assert "missing api key" in r.warnings
    assert "using fallback model" in r.warnings


def test_multiple_runs_produce_distinct_records(tmp_path, fake_subprocess, fake_provision):
    runner.execute(_plan(), _manifest(), workdir=tmp_path)
    runner.execute(_plan(), _manifest(), workdir=tmp_path)
    runner.execute(_plan(), _manifest(), workdir=tmp_path)

    records = RecordManager(tmp_path).list()
    assert len(records) == 3
    run_ids = {r.run_id for r in records}
    assert len(run_ids) == 3  # all unique
