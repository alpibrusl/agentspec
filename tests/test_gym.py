"""Tests for the gym module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentspec.gym import load_task, run_assertions, run_task
from agentspec.gym.task import Task


# ── Task loader ──────────────────────────────────────────────────────────────


def test_load_task_roundtrip(tmp_path: Path):
    src = tmp_path / "t.yaml"
    src.write_text(yaml.safe_dump({"id": "t1", "goal": "do a thing"}))
    task = load_task(src)
    assert task.id == "t1"
    assert task.goal == "do a thing"
    assert task.assertions == []
    assert task.timeout_s == 180


def test_load_task_missing_fields(tmp_path: Path):
    src = tmp_path / "bad.yaml"
    src.write_text(yaml.safe_dump({"id": "only"}))
    with pytest.raises(ValueError, match="missing required"):
        load_task(src)


def test_load_task_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_task(tmp_path / "nope.yaml")


# ── Assertion engine ─────────────────────────────────────────────────────────


def test_file_exists_assertion(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1")
    results = run_assertions(
        tmp_path,
        [
            {"type": "file_exists", "path": "a.py"},
            {"type": "file_exists", "path": "missing.py"},
        ],
    )
    assert results[0].passed is True
    assert results[1].passed is False


def test_file_contains_and_not_contains(tmp_path: Path):
    (tmp_path / "m.py").write_text("def foo():\n    return 1\n")
    results = run_assertions(
        tmp_path,
        [
            {"type": "file_contains", "path": "m.py", "pattern": "def foo"},
            {"type": "file_contains", "path": "m.py", "pattern": "def bar"},
            {"type": "file_not_contains", "path": "m.py", "pattern": "TODO"},
            {"type": "file_not_contains", "path": "m.py", "pattern": "def foo"},
        ],
    )
    assert [r.passed for r in results] == [True, False, True, False]


def test_command_assertion(tmp_path: Path):
    results = run_assertions(
        tmp_path,
        [
            {"type": "command", "cmd": ["true"], "expect_exit": 0},
            {"type": "command", "cmd": ["false"], "expect_exit": 0},
        ],
    )
    assert results[0].passed is True
    assert results[1].passed is False


def test_file_exists_anywhere_finds_nested_file(tmp_path: Path):
    (tmp_path / "proj" / "src").mkdir(parents=True)
    (tmp_path / "proj" / "src" / "api.py").write_text("x = 1")
    results = run_assertions(
        tmp_path,
        [
            {"type": "file_exists_anywhere", "glob": "**/api.py"},
            {"type": "file_exists_anywhere", "glob": "**/missing.py"},
        ],
    )
    assert results[0].passed is True
    assert "proj/src/api.py" in results[0].detail
    assert results[1].passed is False


def test_file_contains_anywhere_matches_any_glob_hit(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "api.py").write_text("no match here")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "api.py").write_text("def read_file(): pass")
    results = run_assertions(
        tmp_path,
        [
            {"type": "file_contains_anywhere", "glob": "**/api.py", "pattern": "read_file"},
            {"type": "file_contains_anywhere", "glob": "**/api.py", "pattern": "missing_fn"},
        ],
    )
    assert results[0].passed is True
    assert results[1].passed is False


def test_command_anywhere_runs_in_nested_project(tmp_path: Path):
    """command_anywhere should cd into the deepest glob match's parent."""
    (tmp_path / "proj").mkdir()
    # Write a marker file the command will detect to prove we cd'd correctly.
    (tmp_path / "proj" / "pyproject.toml").write_text("[project]\nname='x'\n")
    # Also a top-level pyproject; the deeper one should win.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='top'\n")
    results = run_assertions(
        tmp_path,
        [
            {
                "type": "command_anywhere",
                "glob": "**/pyproject.toml",
                "cmd": ["grep", "-q", "name='x'", "pyproject.toml"],
                "expect_exit": 0,
            }
        ],
    )
    assert results[0].passed is True
    assert "proj" in results[0].detail


def test_unknown_assertion_type():
    results = run_assertions(Path("/tmp"), [{"type": "nope"}])
    assert results[0].passed is False
    assert "unknown assertion type" in results[0].detail


# ── End-to-end dry run ───────────────────────────────────────────────────────


def _write_minimal_agent(tmp_path: Path) -> Path:
    """A minimal valid .agent that resolves without any runtime installed."""
    agent = tmp_path / "tiny.agent"
    agent.write_text(
        """
apiVersion: agent/v1
name: tiny-gym-agent
version: 0.1.0
description: A tiny agent used only in the gym test suite.
model:
  capability: reasoning-high
  preferred:
    - claude/claude-sonnet-4-6
skills: []
tools:
  mcp: []
  native: []
""".lstrip()
    )
    return agent


def test_discover_corpus_picks_up_yaml_and_yml(tmp_path: Path):
    from agentspec.gym import discover_corpus

    (tmp_path / "a.yaml").write_text("id: a\ngoal: g\n")
    (tmp_path / "b.yml").write_text("id: b\ngoal: g\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.yaml").write_text("id: c\ngoal: g\n")
    (tmp_path / "notes.md").write_text("ignore me")

    found = discover_corpus(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["a.yaml", "b.yml", "c.yaml"]


def test_run_corpus_aggregates(tmp_path: Path):
    from agentspec.gym import run_corpus

    agent = _write_minimal_agent(tmp_path)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    # One task whose assertion will pass (file is seeded), one whose assertion
    # will fail. Since we use dry_run the agent never actually executes.
    (corpus_dir / "pass.yaml").write_text(
        "id: pass\n"
        "goal: noop\n"
        "setup:\n  files:\n    hi.txt: hello\n"
        "assertions:\n  - type: file_exists\n    path: hi.txt\n"
    )
    (corpus_dir / "fail.yaml").write_text(
        "id: fail\n"
        "goal: noop\n"
        "assertions:\n  - type: file_exists\n    path: missing.txt\n"
    )

    summary = run_corpus(agent, corpus_dir, dry_run=True)
    assert summary.total_tasks == 2
    assert summary.fully_passed == 1
    assert summary.total_assertions == 2
    assert summary.passed_assertions == 1
    assert 0.0 < summary.task_pass_rate < 1.0


def test_run_task_dry_run_with_setup(tmp_path: Path):
    agent = _write_minimal_agent(tmp_path)
    task = Task(
        id="smoke",
        goal="noop",
        setup={"files": {"seeded.txt": "hello"}},
        assertions=[{"type": "file_exists", "path": "seeded.txt"}],
    )

    # Explicit workdir so the seeded file survives for assertion checking.
    workdir = tmp_path / "work"
    workdir.mkdir()
    result = run_task(agent, task, dry_run=True, workdir=workdir)

    assert result.dry_run is True
    assert result.passed == 1
    assert result.failed == 0
    assert result.pass_rate == 1.0
