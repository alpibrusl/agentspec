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
from agentspec.runner.runner import build_command, build_env


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


def _resolve_command(
    manifest, task: Task, dry_run: bool
):
    """Resolve the agent and build its argv + env.

    Returns (argv, env, note). ``env`` carries any provider-specific env
    vars the resolver's auth choice requires — crucially including the
    Vertex-AI env vars when the resolver picked that path, so gemini-cli
    (and claude-code, aider, opencode) actually talk to Vertex instead
    of their direct provider APIs. Without this, a user with
    GOOGLE_CLOUD_PROJECT + ADC set would be routed through Vertex by
    the resolver, but the spawned CLI would fall back to direct-API
    mode and fail because no API key is set.
    """
    try:
        plan = resolve(manifest)
    except RuntimeError as e:
        if not dry_run:
            raise
        return [], os.environ.copy(), f"resolver: {e}"
    argv = build_command(plan, manifest, task.goal)
    env = build_env(plan)
    return argv, env, ""


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
    command, resolved_env, resolver_note = _resolve_command(manifest, task, dry_run)
    ahash = agent_hash(manifest)

    owns_workdir = workdir is None
    workdir = workdir or Path(tempfile.mkdtemp(prefix="agentspec-gym-"))

    stdout_tail = ""
    stderr_tail = resolver_note
    start = time.time()
    try:
        _seed_worktree(workdir, task.setup)

        if not dry_run and command:
            # Start from build_env(plan) which injects Vertex-AI vars
            # when the resolver picked that path, then layer the gym
            # marker on top.
            env = dict(resolved_env)
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


# ── Batch / corpus mode ─────────────────────────────────────────────────────


@dataclass
class BatchSummary:
    """Aggregate across a corpus run."""

    total_tasks: int = 0
    fully_passed: int = 0  # tasks where every assertion passed
    total_assertions: int = 0
    passed_assertions: int = 0
    duration_s: float = 0.0
    results: list[GymResult] = field(default_factory=list)

    @property
    def task_pass_rate(self) -> float:
        return self.fully_passed / self.total_tasks if self.total_tasks else 0.0

    @property
    def assertion_pass_rate(self) -> float:
        return (
            self.passed_assertions / self.total_assertions
            if self.total_assertions
            else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "fully_passed": self.fully_passed,
            "total_assertions": self.total_assertions,
            "passed_assertions": self.passed_assertions,
            "duration_s": round(self.duration_s, 3),
            "task_pass_rate": round(self.task_pass_rate, 3),
            "assertion_pass_rate": round(self.assertion_pass_rate, 3),
            "results": [asdict(r) for r in self.results],
        }


def discover_corpus(corpus_dir: str | Path) -> list[Path]:
    """Return every *.yaml / *.yml task fixture under ``corpus_dir``."""
    root = Path(corpus_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Corpus directory not found: {root}")
    return sorted(p for p in root.rglob("*.y*ml") if p.is_file())


def run_corpus(
    spec_path: str | Path,
    corpus_dir: str | Path,
    *,
    dry_run: bool = False,
) -> BatchSummary:
    """Run every task fixture in ``corpus_dir`` against ``spec_path``."""
    from agentspec.gym.task import load_task  # local import to avoid cycles

    fixtures = discover_corpus(corpus_dir)
    summary = BatchSummary(total_tasks=len(fixtures))
    start = time.time()
    for f in fixtures:
        task = load_task(f)
        result = run_task(spec_path, task, dry_run=dry_run)
        summary.results.append(result)
        summary.total_assertions += result.passed + result.failed
        summary.passed_assertions += result.passed
        if result.failed == 0 and (result.passed > 0):
            summary.fully_passed += 1
    summary.duration_s = time.time() - start
    return summary
