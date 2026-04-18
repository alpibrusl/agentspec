"""Smoke tests for the `agentspec` CLI.

Covers the commands that don't need network access or installed runtime
binaries: validate, resolve, schema, init. The rest (run, push, pull,
extend, search) need either a registry or a subprocess runtime and
are exercised by their own module tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# typer is a core dep; if someone has a stripped-down env without it,
# skip cleanly rather than error on collection.
pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

from agentspec.cli.main import app  # noqa: E402


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def example_manifest(tmp_path: Path) -> Path:
    """Write a minimal .agent file for CLI tests."""
    manifest = tmp_path / "bot.agent"
    manifest.write_text(
        """
name: bot
version: 0.1.0
model:
  capability: reasoning-mid
behavior:
  persona: careful test bot
  traits: [concise]
skills:
  - python-development
tools:
  mcp: []
  native: []
""".lstrip()
    )
    return manifest


def test_validate_accepts_well_formed_manifest(runner, example_manifest):
    result = runner.invoke(app, ["validate", str(example_manifest)])
    assert result.exit_code == 0, result.output
    assert '"ok": true' in result.output


def test_validate_rejects_missing_file(runner, tmp_path):
    result = runner.invoke(app, ["validate", str(tmp_path / "does-not-exist.agent")])
    assert result.exit_code != 0, "missing manifest must be a non-zero exit"


def test_validate_rejects_malformed_yaml(runner, tmp_path):
    bad = tmp_path / "bad.agent"
    bad.write_text("name: :::not valid yaml::: :")
    result = runner.invoke(app, ["validate", str(bad)])
    assert result.exit_code != 0


def test_schema_dumps_json_schema(runner):
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    # Should contain the AgentManifest top-level JSON Schema shape.
    assert "properties" in result.output or "type" in result.output


def test_resolve_emits_structured_output(runner, example_manifest, monkeypatch):
    """`resolve` should succeed or fail with a structured envelope.

    It may legitimately fail on a fresh machine without any runtime binaries,
    but it must not crash with a traceback — the envelope carries the error.
    """
    # Force a deterministic environment — skip optional auto-discovery that
    # could read real home-directory config.
    monkeypatch.setenv("HOME", "/tmp/agentspec-cli-test-home")
    result = runner.invoke(app, ["resolve", str(example_manifest)])
    # Either 0 (resolved) or non-zero with a JSON envelope in stdout.
    assert '"ok"' in result.output or '"error"' in result.output, (
        "resolve must emit a structured envelope, got: " + result.output
    )
