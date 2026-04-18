"""CLI coverage for ``agentspec records {list,show,verify}``.

Uses ``typer.testing.CliRunner`` to drive the commands through the same
ACLI plumbing production users hit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentspec.cli import main as cli
from agentspec.profile.signing import generate_keypair
from agentspec.records.manager import RecordManager, new_run_id
from agentspec.records.models import ExecutionRecord


def _record(run_id: str | None = None, manifest_hash: str = "ag1:aaa") -> ExecutionRecord:
    return ExecutionRecord(
        run_id=run_id or new_run_id(),
        manifest_hash=manifest_hash,
        runtime="claude-code",
        started_at="2026-04-18T14:03:00Z",
        ended_at="2026-04-18T14:07:42Z",
        duration_s=282.13,
        exit_code=0,
        outcome="success",
    )


@pytest.fixture
def runner():
    return CliRunner()


def test_records_list_empty(tmp_path, runner):
    result = runner.invoke(cli.app.typer_app, ["records", "list", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No records" in result.stdout


def test_records_list_shows_entries(tmp_path, runner):
    mgr = RecordManager(tmp_path)
    mgr.write(_record())
    mgr.write(_record())

    result = runner.invoke(cli.app.typer_app, ["records", "list", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    # Two lines, each with claude-code and exit=0.
    assert result.stdout.count("claude-code") == 2
    assert result.stdout.count("exit=0") == 2


def test_records_list_filters_by_manifest(tmp_path, runner):
    mgr = RecordManager(tmp_path)
    mgr.write(_record(manifest_hash="ag1:alpha"))
    mgr.write(_record(manifest_hash="ag1:bravo"))

    result = runner.invoke(
        cli.app.typer_app,
        ["records", "list", "--workdir", str(tmp_path), "--agent", "ag1:alpha"],
    )
    assert result.exit_code == 0
    assert result.stdout.count("claude-code") == 1


def test_records_show_prints_fields(tmp_path, runner):
    mgr = RecordManager(tmp_path)
    r = _record()
    mgr.write(r)

    result = runner.invoke(
        cli.app.typer_app, ["records", "show", r.run_id, "--workdir", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert r.run_id in result.stdout
    assert "claude-code" in result.stdout


def test_records_show_missing_exits_nonzero(tmp_path, runner):
    result = runner.invoke(
        cli.app.typer_app,
        ["records", "show", "01JMISSING000000000000000X", "--workdir", str(tmp_path)],
    )
    assert result.exit_code != 0


def test_records_verify_ok_exits_zero(tmp_path, runner):
    priv, pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _record()
    mgr.write(r, private_key=priv)

    result = runner.invoke(
        cli.app.typer_app,
        ["records", "verify", r.run_id, "--pubkey", pub, "--workdir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_records_verify_invalid_exits_nonzero(tmp_path, runner):
    priv, _ = generate_keypair()
    _, wrong_pub = generate_keypair()
    mgr = RecordManager(tmp_path)
    r = _record()
    mgr.write(r, private_key=priv)

    result = runner.invoke(
        cli.app.typer_app,
        ["records", "verify", r.run_id, "--pubkey", wrong_pub, "--workdir", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "INVALID" in result.stdout


def test_records_list_json_output(tmp_path, runner):
    mgr = RecordManager(tmp_path)
    mgr.write(_record())

    result = runner.invoke(
        cli.app.typer_app,
        ["records", "list", "--workdir", str(tmp_path), "--output", "json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
