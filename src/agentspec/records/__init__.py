"""Execution records — tamper-evident logs of what ran.

See ``docs/proposals/001-execution-records.md`` for the design.

Records are written to ``{workdir}/.agentspec/records/<run-id>.json`` by
the runner when a run completes. Each record captures manifest hash,
timing, exit code, outcome — never prompt content, outputs, or secrets.

When a signing key is provided, the record is wrapped in an Ed25519
envelope (same shape as signed profile memories). Unsigned records are
plain JSON — still evidence, just not attested.
"""

from agentspec.records.manager import RecordManager, new_run_id
from agentspec.records.models import ExecutionRecord

__all__ = ["ExecutionRecord", "RecordManager", "new_run_id"]
