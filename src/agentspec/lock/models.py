"""Pydantic schema for ``agentspec.lock/v1``.

Fields follow ``docs/proposals/001-execution-records.md``. System-prompt
is **never** stored in full — only its sha256 hash — so a lock is safe
to commit to a shared repository. Runtime versions / MCP server
versions are typed as optional strings; the resolver fills them when it
can and leaves them null otherwise.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LockedManifest(BaseModel):
    """Pinned identity of the manifest the lock was built from."""

    model_config = ConfigDict(extra="forbid")
    hash: str = Field(description="Content-addressable hash, ``ag1:...``.")
    name: str
    version: str


class LockedResolved(BaseModel):
    """The frozen output of the resolver for this lock.

    Stored verbatim on disk — other machines replay by loading this
    block back into a ``ResolvedPlan`` instead of calling the resolver.
    """

    model_config = ConfigDict(extra="forbid")
    runtime: str
    runtime_version: str | None = None
    model: str
    tools: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    auth_source: str | None = None
    system_prompt_hash: str = Field(description="sha256:<hex> of the rendered system prompt.")


class LockedHost(BaseModel):
    """Metadata about the machine that produced the lock."""

    model_config = ConfigDict(extra="forbid")
    os: str = Field(description="lowercase platform string, e.g. linux-x86_64.")
    agentspec_version: str


class LockFile(BaseModel):
    """The full on-disk lock document."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )

    schema_: str = Field(
        default="agentspec.lock/v1",
        alias="schema",
        description="Versioned schema identifier — bumped on breaking changes.",
    )
    manifest: LockedManifest
    resolved: LockedResolved
    host: LockedHost
    generated_at: str = Field(description="RFC3339 UTC timestamp of lock creation.")
    warnings: list[str] = Field(default_factory=list)
