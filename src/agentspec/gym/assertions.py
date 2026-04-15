"""Assertion engine for gym tasks.

Supports a small set of check types expressed as dicts in task YAML:

- ``{type: file_exists, path: <rel>}``
- ``{type: file_contains, path: <rel>, pattern: <regex>}``
- ``{type: file_not_contains, path: <rel>, pattern: <regex>}``
- ``{type: file_exists_anywhere, glob: <glob>}`` — recursive glob match
- ``{type: file_contains_anywhere, glob: <glob>, pattern: <regex>}`` — any matching file's content matches regex
- ``{type: command, cmd: [<argv>...], expect_exit: 0}``
- ``{type: command_anywhere, cmd: [...], expect_exit: 0, glob: <glob>}`` — cd into the first glob match, then run

The ``_anywhere`` variants exist so tasks can reward content rather than
punish agents for creating a project subdirectory (``fastapi-anomaly/src/api.py``
should count the same as ``src/api.py`` when the goal didn't constrain paths).
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


def _glob_matches(workdir: Path, pattern: str) -> list[Path]:
    """Recursively glob for files matching ``pattern`` under ``workdir``."""
    if not pattern:
        return []
    # ``rglob`` handles patterns with or without a leading "**/". If the
    # pattern already has a "/", strip any leading "./" but pass through.
    cleaned = pattern.lstrip("./")
    return [p for p in workdir.rglob(cleaned) if p.is_file()]


def _file_exists_anywhere(workdir: Path, spec: dict[str, Any]) -> AssertionResult:
    glob = spec.get("glob") or spec.get("pattern")
    if not glob:
        return AssertionResult(spec, False, "missing 'glob'")
    matches = _glob_matches(workdir, glob)
    if matches:
        rel = matches[0].relative_to(workdir)
        return AssertionResult(spec, True, f"found {rel}")
    return AssertionResult(spec, False, f"no file matching {glob}")


def _file_contains_anywhere(workdir: Path, spec: dict[str, Any]) -> AssertionResult:
    glob = spec.get("glob")
    pattern = spec.get("pattern")
    if not glob or pattern is None:
        return AssertionResult(spec, False, "missing 'glob' or 'pattern'")
    matches = _glob_matches(workdir, glob)
    if not matches:
        return AssertionResult(spec, False, f"no file matching {glob}")
    for m in matches:
        try:
            text = m.read_text(errors="replace")
        except OSError:
            continue
        if re.search(pattern, text):
            rel = m.relative_to(workdir)
            return AssertionResult(spec, True, f"{rel} matched")
    return AssertionResult(
        spec, False, f"no {glob} contained /{pattern}/"
    )


def _command_anywhere(workdir: Path, spec: dict[str, Any]) -> AssertionResult:
    """Run ``cmd`` from the first directory that matches ``glob``.

    Useful when the agent built the project inside a subdirectory — e.g.
    ``glob: "**/pyproject.toml"`` will cd into whichever directory contains
    the pyproject before running pytest there.
    """
    cmd = spec.get("cmd")
    glob = spec.get("glob")
    if not cmd or not isinstance(cmd, list) or not glob:
        return AssertionResult(spec, False, "missing/invalid 'cmd' or 'glob'")
    # Pick the directory that contains the deepest match (preferring
    # nested project dirs over the workdir itself).
    matches = sorted(_glob_matches(workdir, glob), key=lambda p: len(p.parts), reverse=True)
    target_dir = matches[0].parent if matches else workdir
    expect = int(spec.get("expect_exit", 0))
    try:
        result = subprocess.run(
            cmd, cwd=str(target_dir), capture_output=True, text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        return AssertionResult(spec, False, f"timeout running {cmd[0]} in {target_dir}")
    except FileNotFoundError:
        return AssertionResult(spec, False, f"command not found: {cmd[0]}")
    if result.returncode == expect:
        return AssertionResult(
            spec, True, f"ran in {target_dir.relative_to(workdir) if target_dir != workdir else '.'}"
        )
    tail = (result.stderr or result.stdout or "").splitlines()[-1:] or [""]
    return AssertionResult(
        spec, False, f"exit {result.returncode} != {expect} ({tail[0][:80]})"
    )


_HANDLERS = {
    "file_exists": lambda w, s: _file_exists(w, s),
    "file_contains": lambda w, s: _file_contains(w, s, invert=False),
    "file_not_contains": lambda w, s: _file_contains(w, s, invert=True),
    "file_exists_anywhere": lambda w, s: _file_exists_anywhere(w, s),
    "file_contains_anywhere": lambda w, s: _file_contains_anywhere(w, s),
    "command": lambda w, s: _command(w, s),
    "command_anywhere": lambda w, s: _command_anywhere(w, s),
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
