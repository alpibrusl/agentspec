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

# System paths every sandbox needs read-only so the spawned runtime
# (and its dependencies — libc, OpenSSL / CA certs, resolv.conf when
# network is allowed, user/group name lookups) are actually reachable
# inside the sandbox. Discovered via a live smoke run against Ubuntu
# 6.17: without these, ``filesystem: none`` / ``read-only`` / ``scoped``
# fails with ``execvp: No such file or directory`` before the runtime
# CLI even starts. Each candidate is bound only if it exists on the
# host — ``/lib64`` is absent on multiarch Debian, etc.
_SYSTEM_RO_BINDS: tuple[str, ...] = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/lib32",
    "/etc",
)


def _existing_system_ro_binds() -> list[tuple[Path, Path]]:
    """Return the subset of ``_SYSTEM_RO_BINDS`` that exist on this host.

    Prefix-aware dedup: on Ubuntu where ``/bin -> usr/bin`` is a
    symlink, resolving both candidates gives ``/usr`` and ``/usr/bin``.
    A plain set check treats them as distinct, so bwrap ends up with
    the same content mounted at both ``/usr`` and ``/bin``. Checking
    whether a candidate's resolved path is nested inside an already
    committed one drops the redundant bind. Noted in PR #17 third-pass
    review.
    """
    committed: list[Path] = []
    binds: list[tuple[Path, Path]] = []
    for raw in _SYSTEM_RO_BINDS:
        p = Path(raw)
        if not p.exists():
            continue
        resolved = p.resolve()
        # Skip when a parent directory is already committed — that bind
        # already covers this path's contents.
        if any(_is_same_or_descendant(resolved, existing) for existing in committed):
            continue
        committed.append(resolved)
        binds.append((resolved, p))
    return binds


def _is_same_or_descendant(candidate: Path, existing: Path) -> bool:
    """True when ``candidate`` is ``existing`` or lives inside it."""
    if candidate == existing:
        return True
    try:
        candidate.relative_to(existing)
    except ValueError:
        return False
    return True


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

    Intentionally calls ``shutil.which`` via the module attribute — do
    **not** refactor to ``from shutil import which``. Tests
    monkeypatch ``"shutil.which"`` directly to simulate absent / present
    bwrap; a local rebinding would break that and silently couple tests
    to whatever's on the CI host.
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

    .. note::
       Scope paths should live outside the standard system trees
       (``/usr``, ``/bin``, ``/etc``, …). Anything nested under a
       system path is shadowed by the read-only system bind and will
       not be writable even under ``scoped`` — project directories
       like ``~/projects/foo`` or ``/srv/data`` are the intended
       shape.
    """
    # Workdir is always the first rw-bind so ``--chdir`` lands there
    # regardless of how other bindings layer on top. Under
    # ``filesystem: full`` the later ``--bind / /`` covers the same
    # path — harmless but redundant, noted in PR #17 second-pass review.
    rw_binds: list[tuple[Path, Path]] = [(workdir, workdir)]
    ro_binds: list[tuple[Path, Path]] = []

    if trust.filesystem == "full":
        rw_binds.append((Path("/"), Path("/")))
    else:
        # Every bounded-fs mode needs the system binaries + libs + CA
        # trust store + resolv.conf available read-only, or the runtime
        # CLI can't even exec. Surfaced by the PR #17 smoke run.
        ro_binds.extend(_existing_system_ro_binds())
        if trust.filesystem == "read-only":
            for raw in trust.scope:
                p = Path(raw).resolve()
                ro_binds.append((p, p))
        elif trust.filesystem == "scoped":
            for raw in trust.scope:
                p = Path(raw).resolve()
                rw_binds.append((p, p))
        # trust.filesystem == "none" → only system binds + workdir.

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
    env: dict[str, str],
) -> list[str]:
    """Render an ``IsolationPolicy`` + user ``cmd`` into a bwrap argv.

    Flags chosen to match noether PR #34's defaults so the two
    implementations stay close:

    - ``--unshare-all``      — fresh user/PID/mount/UTS/IPC/cgroup ns
    - ``--die-with-parent``  — sandbox reaps if parent exits
    - ``--cap-drop ALL``     — drop every Linux capability
    - ``--clearenv``         — wipe env; rebuild from allowlist only
    - ``--share-net`` only when ``policy.network``

    Mount ordering: ``--proc`` / ``--dev`` / ``--tmpfs /tmp`` are
    emitted **after** binds so later mounts override the binds at the
    specific paths they occupy. Without this, the ``filesystem: full``
    case (which includes ``--bind / /``) shadowed the synthetic
    ``/proc`` mount and exposed the host's ``/proc`` under the fresh
    PID namespace — reported in PR #17 review. The ``filesystem: full``
    path now emits ``--bind / /`` first, then only ``--proc /proc``
    (fresh procfs required for ``--unshare-pid`` consistency); host
    ``/dev`` and ``/tmp`` pass through unchanged.

    Env values are sourced from the ``env`` dict — crucially **not**
    from ``os.environ`` — so layered env (Vertex routing vars, for
    example) reaches the sandboxed runtime. Missing names are dropped
    silently (``--setenv`` with empty value ≠ unset).
    """
    argv: list[str] = [
        bwrap_path,
        "--unshare-all",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--clearenv",
    ]

    if policy.network:
        argv.append("--share-net")

    has_root_bind = any(Path(str(h)) == Path("/") for h, _ in policy.rw_binds)

    if has_root_bind:
        # Host-passthrough mode for ``filesystem: full``. Bind `/` first
        # so subsequent mounts override at their specific paths.
        for host, sandbox in policy.rw_binds:
            argv.extend(["--bind", str(host), str(sandbox)])
        # Still need a fresh procfs because of ``--unshare-pid``.
        argv.extend(["--proc", "/proc"])
    else:
        # Standard sandbox: create the base rootfs (proc/dev/tmp), then
        # layer specific binds on top. RW binds emitted before RO so
        # that when a scope path sits *under* the workdir (e.g. the
        # author wants their RO sample data inside a writable workspace),
        # the RO bind lands last and wins. Surfaced by the PR #17 smoke
        # run.
        argv.extend(
            [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                # /tmp is inside-sandbox — S108 false positive.
                "--tmpfs",
                "/tmp",  # noqa: S108
            ]
        )
        for host, sandbox in policy.rw_binds:
            argv.extend(["--bind", str(host), str(sandbox)])
        for host, sandbox in policy.ro_binds:
            argv.extend(["--ro-bind", str(host), str(sandbox)])

    # Env allowlist. Source from the caller-provided env dict so
    # layered env (Vertex routing, etc.) is honoured, not wiped by
    # --clearenv. See PR #17 review.
    for name in policy.env_allowlist:
        val = env.get(name)
        if val is not None:
            argv.extend(["--setenv", name, val])

    # chdir into the primary RW bind (first one, which is workdir).
    if policy.rw_binds:
        argv.extend(["--chdir", str(policy.rw_binds[0][1])])

    argv.append("--")
    argv.extend(cmd)
    return argv
