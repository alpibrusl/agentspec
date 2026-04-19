"""Coverage for the ``test-echo`` pseudo-runtime.

``test-echo`` exists so demos, integration tests, and CI smoke
scripts have a zero-dependency runtime to exercise the full
push → pull → lock → run → record pipeline without needing
``claude-code`` / ``gemini-cli`` / etc. installed. It's not a real
LLM runtime; it just exec's ``echo``.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from agentspec.parser.manifest import AgentManifest, TrustSpec
from agentspec.resolver.resolver import RUNTIME_BINARIES, PROVIDER_MAP, resolve
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner import runner


def test_test_echo_runtime_binary_is_echo():
    """RUNTIME_BINARIES must list ``test-echo``'s binary so the
    resolver can detect it via ``shutil.which``."""
    assert RUNTIME_BINARIES.get("test-echo") == "echo"


def test_test_echo_provider_entry_has_no_auth():
    """``test-echo`` shouldn't require API keys; nil its way through
    ``PROVIDER_MAP`` with ``None`` for env_keys matches how
    ``ollama`` / ``goose`` work."""
    assert "test-echo" in PROVIDER_MAP
    runtime, env_keys = PROVIDER_MAP["test-echo"]
    assert runtime == "test-echo"
    assert env_keys is None


def test_build_command_dispatches_test_echo():
    """``build_command`` must have a dispatcher for ``test-echo``,
    else ``runner.execute`` raises ``NotImplementedError``."""
    plan = ResolvedPlan(
        runtime="test-echo",
        model="test-echo/demo",
        tools=[],
        auth_source=None,
        system_prompt="",
        warnings=[],
        decisions=[],
    )
    manifest = AgentManifest(
        name="demo",
        version="0.1.0",
        runtime="test-echo",
    )
    cmd = runner.build_command(plan, manifest, "hello from the demo")

    assert cmd[0] == "echo"
    # The prompt appears somewhere in argv so users can see their
    # input in the (mocked) output.
    assert any("hello from the demo" in a for a in cmd), cmd


def test_resolver_picks_test_echo_when_preferred():
    """A manifest whose preferred model starts with ``test-echo/``
    resolves to runtime=test-echo when ``echo`` is on PATH (always true
    on Linux/macOS)."""
    manifest = AgentManifest(
        name="demo",
        version="0.1.0",
        runtime="test-echo",
        model={"preferred": ["test-echo/demo"]},  # type: ignore[arg-type]
    )
    plan = resolve(manifest)
    assert plan.runtime == "test-echo"
    assert plan.model == "test-echo/demo"


def test_execute_with_test_echo_spawns_echo(tmp_path):
    """End-to-end-ish: ``execute()`` with the test-echo runtime
    actually invokes echo, produces exit 0, and writes a record."""
    from agentspec.records.manager import RecordManager

    manifest = AgentManifest(
        name="demo",
        version="0.1.0",
        runtime="test-echo",
        trust=TrustSpec(filesystem="full", network="allowed", exec="full"),
    )
    plan = ResolvedPlan(
        runtime="test-echo",
        model="test-echo/demo",
        tools=[],
        auth_source=None,
        system_prompt="",
        warnings=[],
        decisions=[],
    )
    rc = runner.execute(
        plan,
        manifest,
        input_text="hello smoke",
        workdir=tmp_path,
        via="none",
    )
    assert rc == 0, "test-echo runtime should exit cleanly"

    records = RecordManager(tmp_path).list()
    assert len(records) == 1, "record should be written end-to-end"
    assert records[0].runtime == "test-echo"
    assert records[0].outcome == "success"
