"""Pydantic model for an ExecutionRecord.

Fields match ``docs/proposals/001-execution-records.md``. Core fields are
required; per-run opt-in fields (token_usage, tool_calls, output_digest)
default to None so they stay absent from serialised output when not set.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["success", "failure", "aborted", "timeout"]


class ExecutionRecord(BaseModel):
    """Post-run tamper-evident log of a single ``agentspec run`` invocation."""

    # Pydantic v2: allow the field aliased as "schema" (JSON) while using
    # ``schema_`` internally (``schema`` shadows BaseModel.schema).
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        protected_namespaces=(),
    )

    schema_: str = Field(
        default="agentspec.record/v1",
        alias="schema",
        description="Versioned schema identifier — bumped on breaking changes.",
    )

    run_id: str = Field(description="ULID — sortable, 26 chars, Crockford base32.")
    manifest_hash: str = Field(description="Content-addressable hash of the manifest that ran.")
    lock_hash: str | None = Field(
        default=None,
        description="sha256 of the agentspec.lock that pinned this run, if any.",
    )

    started_at: str = Field(description="RFC3339 UTC timestamp of run start.")
    ended_at: str = Field(description="RFC3339 UTC timestamp of run end.")
    duration_s: float = Field(description="Wall-clock duration in seconds.")

    runtime: str = Field(description="Runtime CLI that was spawned.")
    runtime_version: str | None = None
    model: str | None = None

    exit_code: int = Field(description="Subprocess exit code.")
    outcome: Outcome = Field(
        description="Coarse-grained result — 'success' iff exit_code == 0 by default."
    )
    warnings: list[str] = Field(default_factory=list)

    # Opt-in observability. None when not captured; never prompt/output content.
    token_usage: dict[str, int] | None = Field(
        default=None,
        description="Provider billing counters, e.g. {'input': N, 'output': M}.",
    )
    tool_calls: dict[str, int] | None = Field(
        default=None,
        description="Per-tool invocation counts, e.g. {'web-search': 7}.",
    )
    output_digest: str | None = Field(
        default=None,
        description="sha256:<hex> of a runtime-defined stable output summary.",
    )
