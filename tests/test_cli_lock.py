"""CLI coverage for ``agentspec lock``, ``agentspec verify-lock``, and
``agentspec run --lock``.

Uses ``typer.testing.CliRunner`` through ``cli.app.typer_app``. Subprocess
is monkeypatched via ``runner.subprocess.run`` so no real runtime is
spawned.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agentspec.cli import main as cli
from agentspec.lock.manager import LockManager
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner as runner_mod


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def fake_runtime(monkeypatch):
    """Mock resolver, provisioner and subprocess so CLI tests don't
    depend on API keys, runtimes, or the filesystem beyond tmp_path."""
    calls: list[list[str]] = []

    def _fake_run(cmd, env=None, cwd=None, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0)

    def _fake_resolve(manifest, verbose=False):
        return ResolvedPlan(
            runtime="claude-code",
            model="claude/claude-sonnet-4-6",
            tools=["web-search"],
            auth_source="env.ANTHROPIC_API_KEY",
            system_prompt="test prompt",
            warnings=[],
            decisions=[],
        )

    monkeypatch.setattr(cli, "resolve", _fake_resolve)
    monkeypatch.setattr(runner_mod, "provision", lambda plan, manifest, workdir: None)
    monkeypatch.setattr(runner_mod.subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def agent_file(tmp_path):
    p = tmp_path / "a.agent"
    p.write_text(
        "apiVersion: agent/v1\n"
        "name: lock-cli-test\n"
        "version: 0.1.0\n"
        "runtime: claude-code\n"
    )
    return p


# ── agentspec lock ────────────────────────────────────────────────────────────


def test_lock_creates_file_next_to_manifest(cli_runner, fake_runtime, agent_file):
    result = cli_runner.invoke(cli.app.typer_app, ["lock", str(agent_file)])
    assert result.exit_code == 0, result.stdout

    lock_path = agent_file.with_suffix(agent_file.suffix + ".lock")
    assert lock_path.exists()
    data = json.loads(lock_path.read_text())
    assert data["manifest"]["name"] == "lock-cli-test"
    assert data["resolved"]["runtime"] == "claude-code"


def test_lock_honours_out_flag(cli_runner, fake_runtime, agent_file, tmp_path):
    custom = tmp_path / "custom.lock"
    result = cli_runner.invoke(
        cli.app.typer_app, ["lock", str(agent_file), "--out", str(custom)]
    )
    assert result.exit_code == 0
    assert custom.exists()


# ── agentspec verify-lock ─────────────────────────────────────────────────────


def test_verify_lock_ok_exits_zero(cli_runner, fake_runtime, agent_file, tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()

    # Create signed lock manually since the CLI's --sign flag isn't
    # specified yet — the verify path itself is what we're testing.
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.resolver.resolver import resolve

    # Use fake_runtime's resolver mock to get a plan.
    lock = LockManager.create(load_agent(agent_file), cli.resolve(load_agent(agent_file)))
    lock_path = tmp_path / "x.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["verify-lock", str(lock_path), "--pubkey", pub],
    )
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_verify_lock_invalid_exits_nonzero(cli_runner, fake_runtime, agent_file, tmp_path):
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    _, wrong_pub = generate_keypair()

    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent

    lock = LockManager.create(load_agent(agent_file), cli.resolve(load_agent(agent_file)))
    lock_path = tmp_path / "x.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["verify-lock", str(lock_path), "--pubkey", wrong_pub],
    )
    assert result.exit_code != 0
    assert "INVALID" in result.stdout


# ── agentspec run --lock ──────────────────────────────────────────────────────


def test_run_lock_uses_locked_plan(cli_runner, fake_runtime, agent_file, tmp_path):
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent

    lock = LockManager.create(load_agent(agent_file), cli.resolve(load_agent(agent_file)))
    lock_path = tmp_path / "pinned.lock"
    LockManager.write(lock, lock_path)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--lock", str(lock_path)],
    )

    assert result.exit_code == 0, result.stdout
    # Subprocess got the locked runtime binary.
    assert fake_runtime[0][0] == "claude"


def test_run_lock_rejects_manifest_hash_mismatch(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent

    lock = LockManager.create(load_agent(agent_file), cli.resolve(load_agent(agent_file)))
    # Tamper with the manifest hash so it no longer matches the file.
    lock.manifest.hash = "ag1:ffffffff"
    lock_path = tmp_path / "mismatched.lock"
    LockManager.write(lock, lock_path)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--lock", str(lock_path)],
    )

    assert result.exit_code != 0
    # subprocess.run never called — fail fast before spawning.
    assert fake_runtime == []


def test_run_without_lock_still_resolves(cli_runner, fake_runtime, agent_file):
    result = cli_runner.invoke(cli.app.typer_app, ["run", str(agent_file)])
    assert result.exit_code == 0
    assert fake_runtime[0][0] == "claude"
