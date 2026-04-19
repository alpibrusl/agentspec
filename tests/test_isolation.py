"""Tests for runtime trust enforcement via bubblewrap (proposal 002).

Covers three layers:

1. Policy derivation — ``TrustSpec → IsolationPolicy`` mapping
2. Backend selection — auto / bwrap / none with tight-trust gating
3. Argv rendering — ``IsolationPolicy + cmd → bwrap argv``

No real bwrap is invoked; ``shutil.which`` is monkeypatched and
subprocess calls are observed through the runner integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentspec.parser.manifest import TrustSpec
from agentspec.runner.isolation import (
    IsolationBackend,
    IsolationPolicy,
    build_bwrap_argv,
    find_bwrap,
    is_tight_trust,
    policy_from_trust,
    select_backend,
)


# ── is_tight_trust ────────────────────────────────────────────────────────────


def test_fully_permissive_trust_is_not_tight():
    t = TrustSpec(filesystem="full", network="allowed", exec="full")
    assert is_tight_trust(t) is False


def test_any_restriction_is_tight():
    assert is_tight_trust(TrustSpec(filesystem="none", network="allowed", exec="full"))
    assert is_tight_trust(TrustSpec(filesystem="full", network="none", exec="full"))
    assert is_tight_trust(TrustSpec(filesystem="full", network="allowed", exec="none"))


def test_default_trust_is_tight():
    # Defaults are all 'none' — conservatively tight.
    assert is_tight_trust(TrustSpec())


# ── find_bwrap ────────────────────────────────────────────────────────────────


def test_find_bwrap_returns_path_when_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/fake/path/bwrap" if name == "bwrap" else None)
    assert find_bwrap() == "/fake/path/bwrap"


def test_find_bwrap_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert find_bwrap() is None


# ── select_backend ────────────────────────────────────────────────────────────


def test_select_auto_uses_bwrap_when_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap" if name == "bwrap" else None)
    backend, warning = select_backend(TrustSpec(), requested="auto", allow_unsafe=False)
    assert backend == IsolationBackend.BWRAP
    assert warning is None


def test_select_auto_raises_on_tight_trust_without_bwrap(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="bubblewrap"):
        select_backend(TrustSpec(filesystem="none"), requested="auto", allow_unsafe=False)


def test_select_auto_warns_on_permissive_trust_without_bwrap(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    t = TrustSpec(filesystem="full", network="allowed", exec="full")
    backend, warning = select_backend(t, requested="auto", allow_unsafe=False)
    assert backend == IsolationBackend.NONE
    assert warning is not None
    assert "unsandboxed" in warning.lower() or "no isolation" in warning.lower()


def test_select_bwrap_explicit_raises_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="bwrap"):
        select_backend(TrustSpec(), requested="bwrap", allow_unsafe=False)


def test_select_none_with_tight_trust_requires_unsafe(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    with pytest.raises(RuntimeError, match="unsafe"):
        select_backend(TrustSpec(filesystem="none"), requested="none", allow_unsafe=False)


def test_select_none_with_unsafe_flag_allowed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    backend, warning = select_backend(TrustSpec(filesystem="none"), requested="none", allow_unsafe=True)
    assert backend == IsolationBackend.NONE
    assert warning is not None  # Loud warning expected.


def test_select_none_with_permissive_trust_no_unsafe_needed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/bwrap")
    t = TrustSpec(filesystem="full", network="allowed", exec="full")
    backend, _ = select_backend(t, requested="none", allow_unsafe=False)
    assert backend == IsolationBackend.NONE


# ── policy_from_trust ─────────────────────────────────────────────────────────


def test_policy_fs_none_only_workdir_is_writable(tmp_path):
    p = policy_from_trust(TrustSpec(filesystem="none"), workdir=tmp_path)
    assert (tmp_path, tmp_path) in p.rw_binds
    assert len(p.rw_binds) == 1
    assert p.ro_binds == []


def test_policy_fs_readonly_binds_scope_ro(tmp_path):
    extra = tmp_path / "data"
    extra.mkdir()
    p = policy_from_trust(
        TrustSpec(filesystem="read-only", scope=[str(extra)]),
        workdir=tmp_path,
    )
    # workdir is RW; scope path is RO.
    assert (tmp_path, tmp_path) in p.rw_binds
    assert (extra, extra) in p.ro_binds


def test_policy_fs_scoped_binds_scope_rw(tmp_path):
    extra = tmp_path / "proj"
    extra.mkdir()
    p = policy_from_trust(
        TrustSpec(filesystem="scoped", scope=[str(extra)]),
        workdir=tmp_path,
    )
    assert (extra, extra) in p.rw_binds


def test_policy_fs_full_binds_root_rw(tmp_path):
    p = policy_from_trust(TrustSpec(filesystem="full"), workdir=tmp_path)
    assert (Path("/"), Path("/")) in p.rw_binds


def test_policy_network_none_disables_network(tmp_path):
    p = policy_from_trust(TrustSpec(network="none"), workdir=tmp_path)
    assert p.network is False


def test_policy_network_allowed_enables_network(tmp_path):
    p = policy_from_trust(TrustSpec(network="allowed"), workdir=tmp_path)
    assert p.network is True


def test_policy_network_scoped_enables_with_warning(tmp_path):
    # bwrap v0.7 can't filter egress by host; scoped degrades to 'allowed'
    # (noted in proposal 002, open question 5).
    p = policy_from_trust(TrustSpec(network="scoped"), workdir=tmp_path)
    assert p.network is True


def test_policy_env_always_includes_path(tmp_path):
    p = policy_from_trust(TrustSpec(), workdir=tmp_path)
    assert "PATH" in p.env_allowlist


# ── build_bwrap_argv ──────────────────────────────────────────────────────────


def _minimal_policy(tmp_path: Path) -> IsolationPolicy:
    return IsolationPolicy(
        ro_binds=[],
        rw_binds=[(tmp_path, tmp_path)],
        network=False,
        env_allowlist=["PATH"],
    )


def _setenv_triples(argv: list[str]) -> dict[str, str]:
    """Extract all ``--setenv NAME VALUE`` triples into a dict.

    Safer than substring-matching on ``" ".join(argv)`` — a value that
    contains spaces would pass a naive check spuriously.
    """
    result: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--setenv" and i + 2 < len(argv):
            result[argv[i + 1]] = argv[i + 2]
            i += 3
        else:
            i += 1
    return result


def test_argv_starts_with_bwrap_path(tmp_path):
    argv = build_bwrap_argv("/bin/bwrap", _minimal_policy(tmp_path), ["claude"], {})
    assert argv[0] == "/bin/bwrap"


def test_argv_contains_core_isolation_flags(tmp_path):
    argv = build_bwrap_argv("/bin/bwrap", _minimal_policy(tmp_path), ["claude"], {})
    assert "--unshare-all" in argv
    assert "--die-with-parent" in argv
    assert "--cap-drop" in argv
    assert "--clearenv" in argv


def test_argv_adds_share_net_when_network_true(tmp_path):
    p = _minimal_policy(tmp_path)
    p.network = True
    argv = build_bwrap_argv("/bin/bwrap", p, ["claude"], {})
    assert "--share-net" in argv


def test_argv_omits_share_net_when_network_false(tmp_path):
    argv = build_bwrap_argv("/bin/bwrap", _minimal_policy(tmp_path), ["claude"], {})
    assert "--share-net" not in argv


def test_argv_binds_rw_paths(tmp_path):
    p = _minimal_policy(tmp_path)
    argv = build_bwrap_argv("/bin/bwrap", p, ["claude"], {})
    # --bind <host> <sandbox> for each rw bind
    idx = argv.index("--bind")
    assert argv[idx + 1] == str(tmp_path)
    assert argv[idx + 2] == str(tmp_path)


def test_argv_binds_ro_paths(tmp_path):
    extra = tmp_path / "data"
    p = IsolationPolicy(
        ro_binds=[(extra, extra)],
        rw_binds=[(tmp_path, tmp_path)],
        network=False,
        env_allowlist=[],
    )
    argv = build_bwrap_argv("/bin/bwrap", p, ["claude"], {})
    idx = argv.index("--ro-bind")
    assert argv[idx + 1] == str(extra)
    assert argv[idx + 2] == str(extra)


def test_argv_sets_env_from_env_dict_not_os_environ(tmp_path, monkeypatch):
    """Regression for PR #17 review: values must come from the passed
    ``env`` dict, not ``os.environ``. That's how layered env (Vertex
    routing, for example) reaches the sandboxed runtime after
    ``--clearenv``."""
    # Set host env so the old code would find it there — we want to
    # prove the function sources from the dict instead.
    monkeypatch.setenv("PATH", "/host/path")
    monkeypatch.setenv("VERTEX_PROJECT", "host-project")

    env = {"PATH": "/injected:/bin", "VERTEX_PROJECT": "overridden-project"}
    p = IsolationPolicy(
        ro_binds=[],
        rw_binds=[(tmp_path, tmp_path)],
        network=False,
        env_allowlist=["PATH", "VERTEX_PROJECT"],
    )

    triples = _setenv_triples(build_bwrap_argv("/bin/bwrap", p, ["claude"], env))
    assert triples["PATH"] == "/injected:/bin"
    assert triples["VERTEX_PROJECT"] == "overridden-project"


def test_argv_ends_with_user_command(tmp_path):
    argv = build_bwrap_argv(
        "/bin/bwrap", _minimal_policy(tmp_path), ["claude", "-p", "hi"], {}
    )
    # User command goes after all the bwrap flags.
    assert argv[-3:] == ["claude", "-p", "hi"]


# ── Mount ordering — regression for PR #17 review ────────────────────────────


def test_argv_for_filesystem_full_binds_root_before_proc(tmp_path):
    """``filesystem: full`` emits ``--bind / /`` and a fresh ``/proc``
    after it — not before. If ``--proc`` came first, binding ``/``
    would shadow it and expose the host's procfs under the fresh PID
    namespace, breaking PID consistency."""
    policy = policy_from_trust(TrustSpec(filesystem="full"), workdir=tmp_path)
    argv = build_bwrap_argv("/bin/bwrap", policy, ["claude"], {})

    bind_root_idx = None
    for i in range(len(argv) - 2):
        if argv[i] == "--bind" and argv[i + 1] == "/" and argv[i + 2] == "/":
            bind_root_idx = i
            break
    assert bind_root_idx is not None, f"--bind / / missing from argv: {argv}"

    proc_idx = argv.index("--proc")
    assert bind_root_idx < proc_idx, "--bind / / must precede --proc /proc"


def test_argv_for_filesystem_full_omits_synthetic_tmpfs_and_dev(tmp_path):
    """``filesystem: full`` passes through the host's /dev and /tmp.
    Emitting ``--tmpfs /tmp`` after ``--bind / /`` would create a
    fresh tmpfs that shadows the host /tmp the user asked for."""
    policy = policy_from_trust(TrustSpec(filesystem="full"), workdir=tmp_path)
    argv = build_bwrap_argv("/bin/bwrap", policy, ["claude"], {})
    assert "--tmpfs" not in argv
    assert "--dev" not in argv


def test_argv_for_bounded_fs_creates_base_before_binds(tmp_path):
    """In the standard sandbox (fs != full), special mounts set up the
    base rootfs first and binds layer on top. Order matters because a
    bind under /tmp needs the tmpfs to already exist for bwrap to
    create intermediate dirs."""
    policy = policy_from_trust(TrustSpec(filesystem="none"), workdir=tmp_path)
    argv = build_bwrap_argv("/bin/bwrap", policy, ["claude"], {})

    tmpfs_idx = argv.index("--tmpfs")
    bind_idx = argv.index("--bind")
    assert tmpfs_idx < bind_idx
