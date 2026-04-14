"""Assertion engine for gym tasks.

Supports a small set of check types expressed as dicts in task YAML:

- ``{type: file_exists, path: <rel>}``
- ``{type: file_contains, path: <rel>, pattern: <regex>}``
- ``{type: file_not_contains, path: <rel>, pattern: <regex>}``
- ``{type: command, cmd: [<argv>...], expect_exit: 0}``

Each assertion returns an :class:`AssertionResult`; the runner collects
them and computes a pass rate.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AssertionResult:
    spec: dict[str, Any]
    passed: bool
    detail: str = ""


def _file_exists(workdir: Path, spec: dict[str, Any]) -> AssertionResult:
    rel = spec.get("path")
    if not rel:
        return AssertionResult(spec, False, "missing 'path'")
    exists = (workdir / rel).is_file()
    return AssertionResult(spec, exists, "" if exists else f"{rel} not found")


def _file_contains(workdir: Path, spec: dict[str, Any], invert: bool) -> AssertionResult:
    rel = spec.get("path")
    pattern = spec.get("pattern")
    if not rel or pattern is None:
        return AssertionResult(spec, False, "missing 'path' or 'pattern'")
    target = workdir / rel
    if not target.is_file():
        return AssertionResult(spec, False, f"{rel} not found")
    text = target.read_text(errors="replace")
    matched = re.search(pattern, text) is not None
    passed = matched ^ invert
    if passed:
        return AssertionResult(spec, True)
    verb = "matched" if invert else "did not match"
    return AssertionResult(spec, False, f"{rel} {verb} /{pattern}/")


def _command(workdir: Path, spec: dict[str, Any]) -> AssertionResult:
    cmd = spec.get("cmd")
    if not cmd or not isinstance(cmd, list):
        return AssertionResult(spec, False, "missing/invalid 'cmd'")
    expect = int(spec.get("expect_exit", 0))
    try:
        result = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        return AssertionResult(spec, False, f"timeout running {cmd[0]}")
    except FileNotFoundError:
        return AssertionResult(spec, False, f"command not found: {cmd[0]}")
    if result.returncode == expect:
        return AssertionResult(spec, True)
    tail = (result.stderr or result.stdout or "").splitlines()[-1:] or [""]
    return AssertionResult(
        spec, False, f"exit {result.returncode} != {expect} ({tail[0][:80]})"
    )


_HANDLERS = {
    "file_exists": lambda w, s: _file_exists(w, s),
    "file_contains": lambda w, s: _file_contains(w, s, invert=False),
    "file_not_contains": lambda w, s: _file_contains(w, s, invert=True),
    "command": lambda w, s: _command(w, s),
}


def run_assertions(workdir: Path, assertions: list[dict[str, Any]]) -> list[AssertionResult]:
    """Execute every assertion against the worktree and return results."""
    results: list[AssertionResult] = []
    for spec in assertions:
        atype = spec.get("type")
        handler = _HANDLERS.get(atype)
        if handler is None:
            results.append(AssertionResult(spec, False, f"unknown assertion type: {atype}"))
            continue
        results.append(handler(workdir, spec))
    return results
