"""Gym runner — execute a task against an agent spec and score the result."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agentspec.gym.assertions import AssertionResult, run_assertions
from agentspec.gym.task import Task
from agentspec.parser.loader import agent_hash, load_agent
from agentspec.resolver.resolver import resolve
from agentspec.runner.runner import build_command


@dataclass
class GymResult:
    task_id: str
    agent_hash: str
    passed: int
    failed: int
    duration_s: float
    assertions: list[dict] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    dry_run: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""

    @property
    def pass_rate(self) -> float:
        total = self.passed + self.failed
        return self.passed / total if total else 0.0


def _seed_worktree(workdir: Path, setup: dict) -> None:
    """Populate the worktree from task.setup before the agent runs."""
    files = setup.get("files", {})
    for rel, content in files.items():
        target = workdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def _resolve_command(manifest, task: Task, dry_run: bool) -> tuple[list[str], str]:
    """Resolve the agent and build its argv, or return an empty list + note."""
    try:
        plan = resolve(manifest)
    except RuntimeError as e:
        if not dry_run:
            raise
        return [], f"resolver: {e}"
    return build_command(plan, manifest, task.goal), ""


def run_task(
    spec_path: str | Path,
    task: Task,
    *,
    dry_run: bool = False,
    workdir: Path | None = None,
) -> GymResult:
    """Run a task against an agent spec.

    If ``dry_run`` is True, skips actual agent execution and only evaluates
    assertions against whatever was seeded into the worktree. Useful for
    validating assertion logic without a framework CLI installed.

    If ``workdir`` is provided, runs in it (caller cleans up). Otherwise a
    temporary directory is created and removed afterwards.
    """
    manifest = load_agent(str(spec_path))
    command, resolver_note = _resolve_command(manifest, task, dry_run)
    ahash = agent_hash(manifest)

    owns_workdir = workdir is None
    workdir = workdir or Path(tempfile.mkdtemp(prefix="agentspec-gym-"))

    stdout_tail = ""
    stderr_tail = resolver_note
    start = time.time()
    try:
        _seed_worktree(workdir, task.setup)

        if not dry_run and command:
            env = os.environ.copy()
            env.setdefault("AGENTSPEC_GYM", "1")
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(workdir),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=task.timeout_s,
                )
                stdout_tail = proc.stdout[-2000:]
                stderr_tail = proc.stderr[-2000:]
            except subprocess.TimeoutExpired as e:
                stderr_tail = f"timeout after {task.timeout_s}s"
                stdout_tail = (e.stdout or "")[-2000:] if e.stdout else ""

        results: list[AssertionResult] = run_assertions(workdir, task.assertions)
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return GymResult(
            task_id=task.id,
            agent_hash=ahash,
            passed=passed,
            failed=failed,
            duration_s=round(time.time() - start, 3),
            assertions=[
                {"type": r.spec.get("type"), "passed": r.passed, "detail": r.detail}
                for r in results
            ],
            command=command,
            dry_run=dry_run,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def result_to_json(result: GymResult) -> str:
    return json.dumps(asdict(result), indent=2)
