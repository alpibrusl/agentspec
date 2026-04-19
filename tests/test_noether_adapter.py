"""Tests for the noether-sandbox adapter (Phase 2 of trust enforcement).

Unit tests stay hermetic — they don't spawn the real ``noether-sandbox``
binary. The integration parity test in ``tests/test_noether_smoke.py``
covers the live-spawn path when the binary is available.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentspec.parser.manifest import TrustSpec
from agentspec.runner.isolation import IsolationPolicy, policy_from_trust
from agentspec.runner.noether_adapter import (
    UnsupportedByNoetherAdapter,
    build_noether_argv,
    policy_to_noether_json,
)


# ── policy_to_noether_json ────────────────────────────────────────────────


def test_json_contains_ro_binds_as_named_structs(tmp_path: Path) -> None:
    # noether v0.7.1 moved ro_binds from tuple-form to
    # ``{host, sandbox}`` objects (reviewed in noether#37). The
    # adapter must emit the named-struct form.
    policy = IsolationPolicy(
        ro_binds=[(Path("/usr"), Path("/usr")), (Path("/etc"), Path("/etc"))],
        rw_binds=[(tmp_path, tmp_path)],
        network=False,
        env_allowlist=["PATH"],
    )

    doc = json.loads(policy_to_noether_json(policy, workdir=tmp_path))

    assert doc["ro_binds"] == [
        {"host": "/usr", "sandbox": "/usr"},
        {"host": "/etc", "sandbox": "/etc"},
    ]


def test_json_maps_workdir_to_work_host(tmp_path: Path) -> None:
    # noether's single-rw model expresses the workdir via ``work_host``.
    policy = IsolationPolicy(
        ro_binds=[(Path("/usr"), Path("/usr"))],
        rw_binds=[(tmp_path, tmp_path)],
        network=False,
        env_allowlist=[],
    )

    doc = json.loads(policy_to_noether_json(policy, workdir=tmp_path))

    assert doc["work_host"] == str(tmp_path)


def test_json_preserves_network_and_env_allowlist(tmp_path: Path) -> None:
    policy = IsolationPolicy(
        ro_binds=[],
        rw_binds=[(tmp_path, tmp_path)],
        network=True,
        env_allowlist=["PATH", "HOME", "ANTHROPIC_API_KEY"],
    )

    doc = json.loads(policy_to_noether_json(policy, workdir=tmp_path))

    assert doc["network"] is True
    assert doc["env_allowlist"] == ["PATH", "HOME", "ANTHROPIC_API_KEY"]


def test_json_rejects_extra_rw_binds_beyond_workdir(tmp_path: Path) -> None:
    # noether v0.7.1 has no multi-path rw_binds; refuse rather than
    # silently drop scope paths. Tracked in noether#39.
    scope = tmp_path / "scope-dir"
    scope.mkdir()
    policy = IsolationPolicy(
        ro_binds=[],
        rw_binds=[(tmp_path, tmp_path), (scope, scope)],
        network=False,
        env_allowlist=[],
    )

    with pytest.raises(UnsupportedByNoetherAdapter) as excinfo:
        policy_to_noether_json(policy, workdir=tmp_path)
    assert "noether/issues/39" in str(excinfo.value)


def test_json_rejects_host_passthrough(tmp_path: Path) -> None:
    # ``filesystem: full`` maps to ``--bind / /``; noether-sandbox has
    # no policy flag for host-passthrough. Caller should fall back to
    # direct-bwrap.
    policy = IsolationPolicy(
        ro_binds=[],
        rw_binds=[(tmp_path, tmp_path), (Path("/"), Path("/"))],
        network=True,
        env_allowlist=[],
    )

    with pytest.raises(UnsupportedByNoetherAdapter):
        policy_to_noether_json(policy, workdir=tmp_path)


def test_json_from_trust_none_is_supported(tmp_path: Path) -> None:
    # ``filesystem: none`` — workdir-only rw, system binds ro. The
    # adapter's target mode.
    policy = policy_from_trust(
        TrustSpec(filesystem="none", network="none", exec="full"),
        workdir=tmp_path,
    )
    # Sanity: the derived policy must be adapter-compatible.
    doc = json.loads(policy_to_noether_json(policy, workdir=tmp_path))
    assert doc["work_host"] == str(tmp_path)


def test_json_from_trust_read_only_is_supported(tmp_path: Path) -> None:
    scope = tmp_path / "docs"
    scope.mkdir()
    policy = policy_from_trust(
        TrustSpec(
            filesystem="read-only", network="none", exec="full", scope=[str(scope)]
        ),
        workdir=tmp_path,
    )
    doc = json.loads(policy_to_noether_json(policy, workdir=tmp_path))
    # scope path surfaces as an ro_bind.
    assert {"host": str(scope.resolve()), "sandbox": str(scope.resolve())} in doc[
        "ro_binds"
    ]


def test_json_from_trust_scoped_is_rejected(tmp_path: Path) -> None:
    # ``filesystem: scoped`` adds rw_binds beyond the workdir —
    # unsupported until noether#39 lands.
    scope = tmp_path / "project"
    scope.mkdir()
    policy = policy_from_trust(
        TrustSpec(
            filesystem="scoped", network="none", exec="full", scope=[str(scope)]
        ),
        workdir=tmp_path,
    )
    with pytest.raises(UnsupportedByNoetherAdapter):
        policy_to_noether_json(policy, workdir=tmp_path)


# ── build_noether_argv ────────────────────────────────────────────────────


def test_argv_wraps_inner_cmd_after_dashdash() -> None:
    argv = build_noether_argv(
        "/usr/local/bin/noether-sandbox", ["claude-code", "-p", "hello"]
    )
    assert argv[0] == "/usr/local/bin/noether-sandbox"
    dd = argv.index("--")
    assert argv[dd + 1 :] == ["claude-code", "-p", "hello"]


def test_argv_includes_require_isolation_by_default() -> None:
    argv = build_noether_argv("/usr/bin/noether-sandbox", ["true"])
    assert "--require-isolation" in argv


def test_argv_require_isolation_can_be_disabled() -> None:
    argv = build_noether_argv(
        "/usr/bin/noether-sandbox", ["true"], require_isolation=False
    )
    assert "--require-isolation" not in argv


def test_argv_selects_bwrap_backend() -> None:
    # Adapter always asks for bwrap explicitly; ``auto`` + no bwrap
    # would silently fall through to ``none`` (unless
    # --require-isolation catches it — but we don't rely on that).
    argv = build_noether_argv("/usr/bin/noether-sandbox", ["true"])
    assert "--isolate=bwrap" in argv


def test_argv_policy_file_flag_when_path_given(tmp_path: Path) -> None:
    policy_file = tmp_path / "policy.json"
    argv = build_noether_argv(
        "/usr/bin/noether-sandbox", ["true"], policy_file=policy_file
    )
    idx = argv.index("--policy-file")
    assert argv[idx + 1] == str(policy_file)
