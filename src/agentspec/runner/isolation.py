"""Runtime trust enforcement via bubblewrap (Proposal 002).

Closes the gap between the parse-time trust model (`TrustSpec` — child
can't widen parent) and run-time enforcement (the runner historically
spawned the CLI with host-user privileges).

## Why bwrap and not delegation to noether?

Proposal 002 originally planned to delegate to noether's isolation
(noether PR #34, `IsolationBackend::Bwrap`). That proved unworkable:
``noether run`` executes Lagrange composition graphs, not arbitrary
external commands, and there is no ``noether run-external`` today. We
filed [noether#36](https://github.com/alpibrusl/noether/issues/36)
asking for one; in the meantime we wrap bwrap directly here. When
noether grows the interface, this module becomes a thin adapter.

## Mapping

``TrustSpec`` (filesystem/network/exec axes) → ``IsolationPolicy``
(ro_binds, rw_binds, network, env_allowlist) → bwrap argv. The policy
layer is a normal dataclass so adding a second backend later is mechanical.

## What this does NOT promise

- **Execve blocking** (``trust.exec == "none"``) requires seccomp-bpf,
  which bwrap alone doesn't provide. Phase 2 (native namespaces +
  Landlock + seccomp) would close this; Phase 1 settles for "the
  sandbox's caps are dropped and ``/nix/store`` is ro, so spawning
  anything new requires a binary under a bound path". Documented as
  a known gap — don't rely on Phase 1 to contain a determined exec.
- **Per-URL network allowlists** — ``trust.network == "scoped"``
  degrades to ``allowed`` with a resolver warning. Real egress
  filtering is v0.8+ territory (native backend).
- **macOS / Windows** — bwrap is Linux-only. Callers on other
  platforms get ``IsolationBackend.NONE`` with a platform warning
  from the backend selector.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from agentspec.parser.manifest import TrustSpec


class IsolationBackend(Enum):
    """Which isolation mechanism is active for a run."""

    NONE = "none"
    BWRAP = "bwrap"


@dataclass
class IsolationPolicy:
    """Declarative description of the sandbox surface.

    Rendered into a bwrap argv by ``build_bwrap_argv``. Kept decoupled
    from the renderer so a second backend (e.g. native namespaces +
    Landlock + seccomp) can consume the same policy unchanged.
    """

    ro_binds: list[tuple[Path, Path]]
    rw_binds: list[tuple[Path, Path]]
    network: bool
    env_allowlist: list[str] = field(default_factory=list)


# Env vars that runtimes need to find binaries + locale + CA certs.
# API keys are surfaced via the *plan*'s auth_source and added to the
# allowlist dynamically by the caller — never hardcoded here.
_BASE_ENV_ALLOWLIST = ["PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "USER"]


def is_tight_trust(trust: TrustSpec) -> bool:
    """True when any axis is more restrictive than fully permissive.

    Used to decide whether falling back to ``IsolationBackend.NONE``
    without ``--unsafe-no-isolation`` is an error (tight manifest =
    the declaration means something) or a warning (permissive manifest
    = unsandboxed is effectively what the author asked for).
    """
    return (
        trust.filesystem != "full"
        or trust.network != "allowed"
        or trust.exec != "full"
    )


def find_bwrap() -> str | None:
    """Return the absolute path of ``bwrap`` on PATH, or None.

    Kept trivial so tests monkeypatch ``shutil.which`` directly.
    """
    return shutil.which("bwrap")


def select_backend(
    trust: TrustSpec,
    requested: str | None,
    allow_unsafe: bool,
) -> tuple[IsolationBackend, str | None]:
    """Pick the backend for a run. Returns ``(backend, warning|None)``.

    Rules (matches Proposal 002, open questions 1 and 2, with my
    defaults):

    - ``requested == "bwrap"`` — strict: fail if bwrap not found.
    - ``requested == "none"`` — opt-out: tight trust requires
      ``allow_unsafe`` (else RuntimeError); permissive trust OK.
    - ``requested in {None, "auto"}`` — auto-detect: use bwrap if
      present; if absent and trust is tight, raise; if absent and
      permissive, return NONE with a warning (same UX as today).
    """
    bwrap = find_bwrap()

    if requested == "none":
        if is_tight_trust(trust) and not allow_unsafe:
            raise RuntimeError(
                "--via=none with a manifest that declares non-trivial trust "
                "would silently ignore the declared constraints. Pass "
                "--unsafe-no-isolation to override, or omit --via to auto-detect."
            )
        warning = (
            "isolation disabled by --via=none; subprocess runs with host-user "
            "privileges"
        )
        return IsolationBackend.NONE, warning

    if requested == "bwrap":
        if bwrap is None:
            raise RuntimeError(
                "--via=bwrap but bubblewrap was not found on PATH. Install it "
                "(apt/brew/nix) or pass --via=none --unsafe-no-isolation."
            )
        return IsolationBackend.BWRAP, None

    # Auto-detect (requested is None or "auto").
    if bwrap is not None:
        return IsolationBackend.BWRAP, None

    if is_tight_trust(trust):
        raise RuntimeError(
            "manifest declares non-trivial trust constraints but bubblewrap is "
            "not installed. Install bubblewrap to enable sandboxing, or pass "
            "--unsafe-no-isolation to run unsandboxed anyway."
        )

    return (
        IsolationBackend.NONE,
        "bubblewrap not found; running unsandboxed on a permissive manifest",
    )


def policy_from_trust(
    trust: TrustSpec,
    workdir: Path,
    *,
    extra_env_allowlist: list[str] | None = None,
) -> IsolationPolicy:
    """Derive an ``IsolationPolicy`` from a ``TrustSpec``.

    The workdir is always RW — that's where the provisioner wrote
    instruction files and where records get persisted.

    Filesystem mapping:

    - ``none``       — only workdir RW; nothing else visible
    - ``read-only``  — scope paths RO; workdir RW
    - ``scoped``     — scope paths RW; workdir RW
    - ``full``       — root RW (effectively no filesystem isolation)

    Network mapping: ``none`` disables, ``scoped``/``allowed`` enable.
    (bwrap v1 can't filter egress; ``scoped`` degrades to ``allowed``
    with a resolver warning one level up — documented open question 5.)
    """
    rw_binds: list[tuple[Path, Path]] = [(workdir, workdir)]
    ro_binds: list[tuple[Path, Path]] = []

    if trust.filesystem == "full":
        rw_binds.append((Path("/"), Path("/")))
    elif trust.filesystem == "read-only":
        for raw in trust.scope:
            p = Path(raw).resolve()
            ro_binds.append((p, p))
    elif trust.filesystem == "scoped":
        for raw in trust.scope:
            p = Path(raw).resolve()
            rw_binds.append((p, p))
    # trust.filesystem == "none" → nothing added beyond workdir.

    network = trust.network != "none"

    env = list(_BASE_ENV_ALLOWLIST)
    if extra_env_allowlist:
        for name in extra_env_allowlist:
            if name not in env:
                env.append(name)

    return IsolationPolicy(
        ro_binds=ro_binds,
        rw_binds=rw_binds,
        network=network,
        env_allowlist=env,
    )


def build_bwrap_argv(
    bwrap_path: str,
    policy: IsolationPolicy,
    cmd: list[str],
) -> list[str]:
    """Render an ``IsolationPolicy`` + user ``cmd`` into a bwrap argv.

    Flags chosen to match noether PR #34's defaults so the two
    implementations stay close:

    - ``--unshare-all``      — fresh user/PID/mount/UTS/IPC/cgroup ns
    - ``--die-with-parent``  — sandbox reaps if parent exits
    - ``--cap-drop ALL``     — drop every Linux capability
    - ``--clearenv``         — wipe env; rebuild from allowlist only
    - ``--proc /proc`` / ``--dev /dev`` / ``--tmpfs /tmp`` — minimal
      filesystem expected by most CLIs
    - ``--share-net`` only when ``policy.network``

    Env values are read from ``os.environ`` at build time. Missing
    vars are skipped silently (``--setenv`` with an empty value would
    set the var to empty, which is not the same as "unset").
    """
    argv: list[str] = [
        bwrap_path,
        "--unshare-all",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        # /tmp is the mount point inside the sandbox, not a host path — S108
        # is a false positive here. Bwrap creates a fresh tmpfs.
        "--tmpfs",
        "/tmp",  # noqa: S108
    ]

    if policy.network:
        argv.append("--share-net")

    # RO binds first so a later RW bind at the same path shadows them.
    for host, sandbox in policy.ro_binds:
        argv.extend(["--ro-bind", str(host), str(sandbox)])
    for host, sandbox in policy.rw_binds:
        argv.extend(["--bind", str(host), str(sandbox)])

    # Env allowlist.
    for name in policy.env_allowlist:
        val = os.environ.get(name)
        if val is not None:
            argv.extend(["--setenv", name, val])

    # chdir into the primary RW bind (first one, which is workdir).
    if policy.rw_binds:
        argv.extend(["--chdir", str(policy.rw_binds[0][1])])

    argv.append("--")
    argv.extend(cmd)
    return argv
