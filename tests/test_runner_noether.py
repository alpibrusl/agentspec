"""Runner integration tests for the noether-sandbox adapter path.

``AGENTSPEC_ISOLATION_BACKEND=noether`` flips the execution path from
the direct bwrap wrapper to an adapter that writes the policy to a
tmpfile and spawns ``noether-sandbox``. These tests monkeypatch
``shutil.which`` and ``subprocess.run`` so no real binary is spawned.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentspec.parser.manifest import AgentManifest, TrustSpec
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner


@pytest.fixture
def fake_provision(monkeypatch):
    monkeypatch.setattr(runner, "provision", lambda plan, manifest, workdir: None)


@pytest.fixture
def fake_run(monkeypatch):
    calls: list[dict] = []

    def _fake(cmd, env=None, cwd=None, **kwargs):
        calls.append({"cmd": cmd, "env": env, "cwd": cwd, "kwargs": kwargs})
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
        name="noether-test",
        version="0.1.0",
        runtime="claude-code",
        trust=trust or TrustSpec(filesystem="none", network="none", exec="full"),
    )


def _which_stub(mapping: dict[str, str | None]):
    """shutil.which stub: returns ``mapping.get(name)`` for any binary."""
    def _inner(name: str, *args, **kwargs):
        return mapping.get(name)
    return _inner


# ── Opt-in via env var ────────────────────────────────────────────────────


def test_noether_backend_env_var_uses_noether_sandbox(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setenv("AGENTSPEC_ISOLATION_BACKEND", "noether")
    monkeypatch.setattr(
        "shutil.which",
        _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": "/usr/bin/noether-sandbox"}),
    )

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="none", network="none", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    assert argv[0] == "/usr/bin/noether-sandbox"
    assert "--isolate=bwrap" in argv
    assert "--require-isolation" in argv
    # Inner cmd must appear after ``--``.
    assert argv[argv.index("--") + 1] == "claude"


def test_noether_backend_writes_policy_file_with_expected_shape(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.setenv("AGENTSPEC_ISOLATION_BACKEND", "noether")
    monkeypatch.setattr(
        "shutil.which",
        _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": "/usr/bin/noether-sandbox"}),
    )

    # Keep the policy file around so the test can read it. The runner
    # would normally unlink after spawn; override that.
    preserved: list[Path] = []
    orig_unlink = runner.Path.unlink  # may or may not be patched; we intercept below

    def _keep_unlink(self, *a, **kw):
        preserved.append(Path(self))
        # Don't actually unlink; test reads the file after execute().

    monkeypatch.setattr(runner.Path, "unlink", _keep_unlink)

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="none", network="none", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    pf_idx = argv.index("--policy-file")
    policy_path = Path(argv[pf_idx + 1])
    assert policy_path.exists(), f"policy file not written: {policy_path}"

    doc = json.loads(policy_path.read_text())
    # Round-trip shape: named-struct ro_binds + work_host.
    assert doc["work_host"] == str(tmp_path)
    assert all(set(b.keys()) == {"host", "sandbox"} for b in doc["ro_binds"])
    assert doc["network"] is False
    # Policy file was at least scheduled for cleanup.
    assert policy_path in preserved


def test_noether_backend_falls_back_when_binary_missing(
    tmp_path, fake_provision, fake_run, monkeypatch, caplog
):
    monkeypatch.setenv("AGENTSPEC_ISOLATION_BACKEND", "noether")
    # bwrap present, noether-sandbox absent → fall back to direct path.
    monkeypatch.setattr(
        "shutil.which", _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": None})
    )
    caplog.set_level(logging.WARNING, logger="agentspec.runner.runner")

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="none", network="none", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    assert argv[0] == "/usr/bin/bwrap"  # direct path
    assert any("noether-sandbox" in r.message for r in caplog.records), (
        f"expected a fallback warning mentioning noether-sandbox; got "
        f"{[r.message for r in caplog.records]}"
    )


def test_noether_backend_delegates_scoped_trust(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    # noether v0.7.2 (PR noether#47) landed ``rw_binds``, so
    # ``filesystem: scoped`` no longer needs the fallback path.
    monkeypatch.setenv("AGENTSPEC_ISOLATION_BACKEND", "noether")
    monkeypatch.setattr(
        "shutil.which",
        _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": "/usr/bin/noether-sandbox"}),
    )

    # Preserve the policy tmpfile so the test can inspect its contents;
    # runner.execute normally unlinks it after subprocess returns.
    monkeypatch.setattr(runner.Path, "unlink", lambda self, *a, **kw: None)

    scope = tmp_path / "project"
    scope.mkdir()

    runner.execute(
        _plan(),
        _manifest(
            TrustSpec(
                filesystem="scoped", network="none", exec="full", scope=[str(scope)]
            )
        ),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    assert argv[0] == "/usr/bin/noether-sandbox"

    # Verify the scope path crossed as an rw_binds entry in the policy
    # file handed to noether-sandbox.
    pf_idx = argv.index("--policy-file")
    doc = json.loads(Path(argv[pf_idx + 1]).read_text())
    assert {"host": str(scope.resolve()), "sandbox": str(scope.resolve())} in doc[
        "rw_binds"
    ]


def test_noether_backend_still_falls_back_on_filesystem_full(
    tmp_path, fake_provision, fake_run, monkeypatch, caplog
):
    # ``filesystem: full`` is ``--bind / /`` host-passthrough — noether
    # still has no schema for it, so this fallback stays.
    monkeypatch.setenv("AGENTSPEC_ISOLATION_BACKEND", "noether")
    monkeypatch.setattr(
        "shutil.which",
        _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": "/usr/bin/noether-sandbox"}),
    )
    caplog.set_level(logging.WARNING, logger="agentspec.runner.runner")

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="full", network="allowed", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    assert argv[0] == "/usr/bin/bwrap"
    assert any(
        "noether" in r.message.lower() and "fallback" in r.message.lower()
        for r in caplog.records
    )


def test_without_env_var_direct_bwrap_path_unchanged(
    tmp_path, fake_provision, fake_run, monkeypatch
):
    monkeypatch.delenv("AGENTSPEC_ISOLATION_BACKEND", raising=False)
    monkeypatch.setattr(
        "shutil.which",
        _which_stub({"bwrap": "/usr/bin/bwrap", "noether-sandbox": "/usr/bin/noether-sandbox"}),
    )

    runner.execute(
        _plan(),
        _manifest(TrustSpec(filesystem="none", network="none", exec="full")),
        workdir=tmp_path,
        emit_record=False,
    )

    argv = fake_run[0]["cmd"]
    # Default path: direct bwrap even though noether-sandbox is on PATH.
    assert argv[0] == "/usr/bin/bwrap"
