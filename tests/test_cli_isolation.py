"""CLI coverage for --via / --unsafe-no-isolation on `agentspec run`.

Uses typer.testing.CliRunner through the same app.typer_app plumbing
used by other CLI tests. The actual subprocess is monkeypatched so no
runtime CLI is spawned.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agentspec.cli import main as cli
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner as runner_mod


@pytest.fixture
def fake_runtime(monkeypatch, tmp_path):
    """Block the provisioner + resolver + subprocess spawn.

    ``resolve()`` is stubbed to a ResolvedPlan so we don't depend on
    API keys being in env; ``provision()`` is a no-op; ``subprocess.run``
    is captured so tests can assert on the argv that was about to be
    spawned.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd, env=None, cwd=None, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0)

    def _fake_resolve(manifest, verbose=False):
        return ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            tools=[],
            auth_source="env.ANTHROPIC_API_KEY",
            system_prompt="",
            warnings=[],
            decisions=[],
        )

    monkeypatch.setattr(cli, "resolve", _fake_resolve)
    monkeypatch.setattr(runner_mod, "provision", lambda plan, manifest, workdir: None)
    monkeypatch.setattr(runner_mod.subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def agent_file(tmp_path):
    """Write a permissive-trust agent to a temp file."""
    p = tmp_path / "a.agent"
    p.write_text(
        "apiVersion: agent/v1\n"
        "name: cli-iso-test\n"
        "version: 0.1.0\n"
        "runtime: claude-code\n"
        "trust:\n"
        "  filesystem: full\n"
        "  network: allowed\n"
        "  exec: full\n"
    )
    return p


@pytest.fixture
def tight_agent_file(tmp_path):
    p = tmp_path / "tight.agent"
    p.write_text(
        "apiVersion: agent/v1\n"
        "name: tight-iso\n"
        "version: 0.1.0\n"
        "runtime: claude-code\n"
        "trust:\n"
        "  filesystem: none\n"
        "  network: none\n"
        "  exec: none\n"
    )
    return p


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_run_via_bwrap_wraps_command(cli_runner, fake_runtime, agent_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--via", "bwrap"],
    )

    # SystemExit 0 is the happy path — subprocess mocked returncode=0.
    assert result.exit_code == 0, result.stdout
    assert fake_runtime[0][0] == "/bin/bwrap"


def test_run_via_none_with_permissive_trust_ok(
    cli_runner, fake_runtime, agent_file, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--via", "none"],
    )

    assert result.exit_code == 0
    # Not wrapped — first argv element should be the runtime binary.
    assert fake_runtime[0][0] == "claude"


def test_run_via_none_on_tight_trust_without_unsafe_errors(
    cli_runner, fake_runtime, tight_agent_file, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(tight_agent_file), "--via", "none"],
    )

    assert result.exit_code != 0
    # subprocess.run was never called.
    assert fake_runtime == []


def test_run_via_none_with_unsafe_flag_on_tight_trust_proceeds(
    cli_runner, fake_runtime, tight_agent_file, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(tight_agent_file), "--via", "none", "--unsafe-no-isolation"],
    )

    assert result.exit_code == 0
    assert fake_runtime[0][0] == "claude"


def test_run_env_var_fallback_for_via(
    cli_runner, fake_runtime, agent_file, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    monkeypatch.setenv("AGENTSPEC_ISOLATION", "none")

    # Trust is permissive so --via=none without explicit flag works.
    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file)],
    )

    assert result.exit_code == 0
    assert fake_runtime[0][0] == "claude"  # not wrapped


def test_run_via_bwrap_missing_raises_precondition(
    cli_runner, fake_runtime, agent_file, monkeypatch
):
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--via", "bwrap"],
    )

    assert result.exit_code != 0
    assert fake_runtime == []
