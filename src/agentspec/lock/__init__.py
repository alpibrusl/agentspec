"""Lockfiles — the 'pin the setup' half of proposal 001.

A lockfile captures the resolver's output (runtime, model, tools,
auth source, system-prompt hash) + detected host info so another
machine can reproduce the **setup** — not the model output, which
isn't deterministic anyway.

See ``docs/proposals/001-execution-records.md`` for the framing. This
module pairs with ``agentspec.records``: a run produced from a lock
carries ``lock_hash`` in its execution record, giving the audit trail
``manifest → lock → record``.

Public API:

- ``LockFile`` — Pydantic model; ``schema_`` aliases to JSON ``schema``.
- ``LockManager.create(manifest, plan)`` — build a LockFile.
- ``LockManager.write(lock, path, private_key=None)`` — persist.
- ``LockManager.load(path)`` — read (signed or unsigned transparently).
- ``LockManager.verify(path, public_key_hex)`` — Ed25519 check.
- ``plan_from_lock(lock)`` — rehydrate a ResolvedPlan for ``run --lock``.
"""

from agentspec.lock.manager import LockManager, plan_from_lock
from agentspec.lock.models import LockedHost, LockedManifest, LockedResolved, LockFile

__all__ = [
    "LockFile",
    "LockManager",
    "LockedHost",
    "LockedManifest",
    "LockedResolved",
    "plan_from_lock",
]
