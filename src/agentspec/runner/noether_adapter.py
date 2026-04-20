"""Adapter: delegate sandboxing to the ``noether-sandbox`` binary.

Phase 2 of Proposal 002. The direct ``build_bwrap_argv`` path from
v0.5.0 stays the default; callers can opt in to the noether-backed
path via ``AGENTSPEC_ISOLATION_BACKEND=noether``. Once parity is
proven in the wild we'll flip the default.

Why a second path at all? noether (since v0.7.1) ships the same
sandbox primitive we built directly, with TLS dual-path handling,
trusted-PATH bwrap resolution, UID-to-nobody mapping, and a few
hardening niceties (``NOETHER_REQUIRE_ISOLATION`` fail-closed, ``128 +
signum`` exit-code convention) that agentspec would otherwise keep
chasing in parallel. Delegating means one upstream implementation for
both noether stage execution and agentspec trust enforcement.

Scope today:

- ``TrustSpec.filesystem`` values ``none`` / ``read-only`` / ``scoped``
  all delegate via ``noether-sandbox`` v0.7.2+. Workdir renders as
  ``work_host``; extra scope paths cross as ``rw_binds`` (the struct
  added in noether#47).
- ``full`` is host-passthrough (``--bind / /``); noether-sandbox has
  no schema for it. :class:`UnsupportedByNoetherAdapter` is raised so
  the caller can fall back to the direct-bwrap path.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentspec.runner.isolation import IsolationPolicy


class UnsupportedByNoetherAdapter(RuntimeError):
    """Policy can't be expressed in the noether-isolation schema.

    Raised for shapes noether-sandbox v0.7.1 doesn't yet support
    (``filesystem: scoped``, ``filesystem: full``). The caller should
    catch this and fall back to the direct-bwrap path.
    """


def find_noether_sandbox() -> str | None:
    """Locate ``noether-sandbox`` on PATH.

    Not cached; PATH can change across runs (tests monkeypatch it,
    shells prepend nix-profile bins, etc.).
    """
    return shutil.which("noether-sandbox")


def policy_to_noether_json(policy: IsolationPolicy, workdir: Path) -> str:
    """Serialise an agentspec policy to noether-isolation's wire format.

    The mapping:

    - agentspec ``ro_binds`` → noether ``ro_binds`` as
      ``{"host": ..., "sandbox": ...}`` structs (shape pinned in
      noether#37).
    - agentspec's workdir (the primary rw mount, always first in
      ``policy.rw_binds`` by ``policy_from_trust`` construction) →
      noether ``work_host``. Inside the sandbox, workdir appears at
      ``/work``.
    - Any *additional* rw mount (``filesystem: scoped`` scope paths)
      → noether ``rw_binds`` (shape added in noether#47, v0.7.2).
    - A ``--bind / /`` rw entry (``filesystem: full``) has no
      expressible form in noether-isolation's schema. Raises
      :class:`UnsupportedByNoetherAdapter` so the runner falls back
      to the direct-bwrap path.
    """
    workdir_resolved = workdir.resolve()
    extra_rw: list[dict[str, str]] = []
    for host, sandbox in policy.rw_binds:
        host_path = Path(str(host))
        if host_path == Path("/"):
            raise UnsupportedByNoetherAdapter(
                "noether-sandbox has no host-passthrough (``filesystem: full``) "
                "mode; caller should fall back to the direct-bwrap path"
            )
        if host_path.resolve() == workdir_resolved:
            # First entry is workdir — represented via ``work_host``,
            # not ``rw_binds``. Skip here so a naïvely-constructed
            # policy with a duplicate workdir entry doesn't produce
            # a spurious rw_binds item either.
            continue
        extra_rw.append({"host": str(host), "sandbox": str(sandbox)})

    doc = {
        "ro_binds": [
            {"host": str(host), "sandbox": str(sandbox)}
            for host, sandbox in policy.ro_binds
        ],
        "rw_binds": extra_rw,
        "work_host": str(workdir),
        "network": policy.network,
        "env_allowlist": list(policy.env_allowlist),
    }
    return json.dumps(doc, sort_keys=True)


def build_noether_argv(
    noether_bin: str,
    cmd: list[str],
    *,
    require_isolation: bool = True,
    policy_file: Path | None = None,
) -> list[str]:
    """Build the argv to spawn noether-sandbox around ``cmd``.

    Default posture is locked-down: ``--isolate=bwrap`` (no silent
    fallback to ``none``) and ``--require-isolation`` (hard-fail if
    bwrap isn't resolvable at run time). Callers wanting looser
    defaults pass ``require_isolation=False``.

    ``policy_file`` lets the caller write the policy to a tmpfile and
    leave stdin free for the child process — the recommended path for
    any CLI that reads from stdin. Omit it to feed the policy on stdin.
    """
    argv = [noether_bin, "--isolate=bwrap"]
    if require_isolation:
        argv.append("--require-isolation")
    if policy_file is not None:
        argv.extend(["--policy-file", str(policy_file)])
    argv.append("--")
    argv.extend(cmd)
    return argv
