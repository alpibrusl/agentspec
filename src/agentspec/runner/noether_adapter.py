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

- ``TrustSpec.filesystem`` values ``none`` / ``read-only`` map cleanly
  into noether's (``ro_binds``, ``work_host``) shape.
- ``scoped`` needs multi-path rw mounts, which noether-isolation v0.7.1
  doesn't expose. Tracked upstream in noether#39; the adapter raises
  :class:`UnsupportedByNoetherAdapter` so the caller can fall back.
- ``full`` is host-passthrough; there is no noether-sandbox flag for
  it. Same rejection path.
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
      ``{"host": ..., "sandbox": ...}`` structs (shape pinned by
      noether#37).
    - agentspec's workdir (the primary rw mount) → noether ``work_host``.
      Inside the sandbox, workdir appears at ``/work``.
    - Any rw bind **beyond** workdir triggers
      :class:`UnsupportedByNoetherAdapter` — v0.7.1 noether has one
      rw slot, not many. Silent dropping would defeat the agent's
      declared trust.
    - A ``--bind / /`` rw entry (``filesystem: full``) triggers the
      same error for the same reason.
    """
    workdir_resolved = workdir.resolve()
    extra_rw: list[tuple[Path, Path]] = []
    for host, _sandbox in policy.rw_binds:
        if Path(str(host)) == Path("/"):
            raise UnsupportedByNoetherAdapter(
                "noether-sandbox has no host-passthrough (``filesystem: full``) "
                "mode; caller should fall back to the direct-bwrap path"
            )
        if Path(str(host)).resolve() != workdir_resolved:
            extra_rw.append((host, _sandbox))

    if extra_rw:
        raise UnsupportedByNoetherAdapter(
            f"noether-sandbox (v0.7.1) has no multi-rw-bind support; "
            f"refusing to silently drop {len(extra_rw)} scoped rw mount(s). "
            f"Tracked in https://github.com/alpibrusl/noether/issues/39. "
            f"Falling back to the direct-bwrap path preserves the declared trust."
        )

    doc = {
        "ro_binds": [
            {"host": str(host), "sandbox": str(sandbox)}
            for host, sandbox in policy.ro_binds
        ],
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
