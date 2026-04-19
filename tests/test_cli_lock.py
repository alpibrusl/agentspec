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

    # Pin bwrap absence so these lock-focused tests don't vary between
    # hosts that have bwrap and hosts that don't. Isolation has its own
    # test file; here we only care about the lock path through the CLI.
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(cli, "resolve", _fake_resolve)
    monkeypatch.setattr(runner_mod, "provision", lambda plan, manifest, workdir: None)
    monkeypatch.setattr(runner_mod.subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def agent_file(tmp_path):
    # Permissive trust so these lock-focused tests don't trip isolation
    # gating when the host / CI runner has no bwrap on PATH. Isolation
    # coverage lives in test_cli_isolation.py.
    p = tmp_path / "a.agent"
    p.write_text(
        "apiVersion: agent/v1\n"
        "name: lock-cli-test\n"
        "version: 0.1.0\n"
        "runtime: claude-code\n"
        "trust:\n"
        "  filesystem: full\n"
        "  network: allowed\n"
        "  exec: full\n"
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


# ── PR #18 review — ship-blocker regressions ──────────────────────────────────


def test_lock_sign_key_env_produces_signed_envelope(
    cli_runner, fake_runtime, agent_file, tmp_path, monkeypatch
):
    """The CLI must be able to produce signed locks without dropping to
    the Python API. PR #18 review called the Python-only path a
    usability gap."""
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    monkeypatch.setenv("AGENTSPEC_LOCK_SIGNING_KEY", priv)

    out = tmp_path / "signed.lock"
    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "lock",
            str(agent_file),
            "--out",
            str(out),
            "--sign-key-env",
            "AGENTSPEC_LOCK_SIGNING_KEY",
        ],
    )
    assert result.exit_code == 0, result.stdout

    envelope = json.loads(out.read_text())
    assert envelope["algorithm"] == "ed25519"
    assert envelope["public_key"] == pub
    assert len(envelope["signature"]) == 128


def test_run_lock_require_signed_rejects_unsigned_lock(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    """`--require-signed` turns a missing signature into a hard error —
    you can't get a lock through the gate without at minimum declaring
    it's signed. PR #18 review ship-blocker regression."""
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.profile.signing import generate_keypair

    lock = LockManager.create(
        load_agent(agent_file), cli.resolve(load_agent(agent_file))
    )
    lock_path = tmp_path / "unsigned.lock"
    LockManager.write(lock, lock_path)  # unsigned

    _, pub = generate_keypair()
    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "run",
            str(agent_file),
            "--lock",
            str(lock_path),
            "--require-signed",
            "--pubkey",
            pub,
        ],
    )
    assert result.exit_code != 0
    assert fake_runtime == []  # never spawned


def test_run_lock_require_signed_rejects_tampered_signed_lock(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    """The core ship-blocker fix: a signed lock whose `resolved` fields
    have been swapped (but `manifest.hash` untouched) must not run. The
    pre-fix `run --lock` happily used the tampered plan because it only
    checked manifest-hash drift on the user side, never signature."""
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    lock = LockManager.create(
        load_agent(agent_file), cli.resolve(load_agent(agent_file))
    )
    lock_path = tmp_path / "signed.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    # Swap the model inside the signed payload and rewrite the file.
    data = json.loads(lock_path.read_text())
    data["payload"]["resolved"]["model"] = "attacker/rogue-model"
    lock_path.write_text(json.dumps(data))

    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "run",
            str(agent_file),
            "--lock",
            str(lock_path),
            "--require-signed",
            "--pubkey",
            pub,
        ],
    )
    assert result.exit_code != 0
    assert fake_runtime == []


def test_run_lock_require_signed_accepts_valid_signature(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    """Happy path: signed lock + matching pubkey → runs."""
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.profile.signing import generate_keypair

    priv, pub = generate_keypair()
    lock = LockManager.create(
        load_agent(agent_file), cli.resolve(load_agent(agent_file))
    )
    lock_path = tmp_path / "signed.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "run",
            str(agent_file),
            "--lock",
            str(lock_path),
            "--require-signed",
            "--pubkey",
            pub,
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert fake_runtime[0][0] == "claude"


def test_verify_lock_malformed_pubkey_is_precondition_error(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    """Bad hex in --pubkey is operator error, not a tampering signal.
    Conflating the two was a PR #18 review nit — distinct error now."""
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    lock = LockManager.create(
        load_agent(agent_file), cli.resolve(load_agent(agent_file))
    )
    lock_path = tmp_path / "x.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    result = cli_runner.invoke(
        cli.app.typer_app,
        ["verify-lock", str(lock_path), "--pubkey", "not-hex-at-all"],
    )
    assert result.exit_code != 0
    # Message should not say "INVALID" alone — that conflates with real
    # signature failures.
    assert "INVALID" not in result.stdout or "pubkey" in result.stdout.lower()


# ── PR #18 round-2 review polish ──────────────────────────────────────────────


def test_verify_lock_short_pubkey_is_operator_error(
    cli_runner, fake_runtime, agent_file, tmp_path
):
    """Round-2 review: `bytes.fromhex("ab")` succeeds (2 bytes) but
    fails inside VerifyKey as an internal ValueError → reported as
    INVALID, indistinguishable from tampering. Length check up front
    now makes truncated-paste distinct from real signature mismatch."""
    from agentspec.lock.manager import LockManager
    from agentspec.parser.loader import load_agent
    from agentspec.profile.signing import generate_keypair

    priv, _ = generate_keypair()
    lock = LockManager.create(
        load_agent(agent_file), cli.resolve(load_agent(agent_file))
    )
    lock_path = tmp_path / "x.lock"
    LockManager.write(lock, lock_path, private_key=priv)

    # 2-byte hex is "valid hex" but wrong length.
    result = cli_runner.invoke(
        cli.app.typer_app,
        ["verify-lock", str(lock_path), "--pubkey", "ab"],
    )
    assert result.exit_code != 0
    # Not INVALID — that's reserved for actual signature mismatches.
    assert "INVALID" not in result.stdout


def test_lock_sign_key_env_garbage_is_operator_error(
    cli_runner, fake_runtime, agent_file, tmp_path, monkeypatch
):
    """Round-2 review: garbage in the --sign-key-env env var used to
    surface as an ugly PyNaCl traceback. Validate at the CLI boundary
    so the user gets a clean error pointing at their env var."""
    monkeypatch.setenv("AGENTSPEC_LOCK_SIGNING_KEY", "not-hex-at-all")

    out = tmp_path / "signed.lock"
    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "lock",
            str(agent_file),
            "--out",
            str(out),
            "--sign-key-env",
            "AGENTSPEC_LOCK_SIGNING_KEY",
        ],
    )
    assert result.exit_code != 0
    # Clean error surface — should not have dumped a traceback.
    assert not out.exists()


def test_lock_sign_key_env_wrong_length_is_operator_error(
    cli_runner, fake_runtime, agent_file, tmp_path, monkeypatch
):
    """Round-2 review: wrong-length hex (valid chars, wrong byte count)
    must fail with a pointer to the operator, not a cryptic PyNaCl
    error."""
    monkeypatch.setenv("AGENTSPEC_LOCK_SIGNING_KEY", "abab")  # 2 bytes

    out = tmp_path / "signed.lock"
    result = cli_runner.invoke(
        cli.app.typer_app,
        [
            "lock",
            str(agent_file),
            "--out",
            str(out),
            "--sign-key-env",
            "AGENTSPEC_LOCK_SIGNING_KEY",
        ],
    )
    assert result.exit_code != 0
    assert not out.exists()


def test_run_require_signed_without_lock_is_operator_error(
    cli_runner, fake_runtime, agent_file
):
    """Round-2 review: `--require-signed` without `--lock` used to be
    silently ignored (user thought they were refusing unsigned runs;
    actually got the normal resolve path). Explicit error closes the
    loop."""
    from agentspec.profile.signing import generate_keypair

    _, pub = generate_keypair()
    result = cli_runner.invoke(
        cli.app.typer_app,
        ["run", str(agent_file), "--require-signed", "--pubkey", pub],
    )
    assert result.exit_code != 0
    assert fake_runtime == []  # never spawned
