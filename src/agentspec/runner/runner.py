"""Runner — spawns the resolved runtime with the agent's configuration.

Translates a ResolvedPlan into the actual CLI invocation for the
selected runtime (claude-code, gemini-cli, codex-cli, etc.).

Before spawning, the provisioner writes runtime-specific config files
(instruction files, MCP configs) so each CLI receives the agent's
identity, rules, skill instructions, and tool registrations natively.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from agentspec.parser.loader import agent_hash
from agentspec.parser.manifest import AgentManifest
from agentspec.records.manager import RecordManager, new_run_id
from agentspec.records.models import ExecutionRecord
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.resolver.vertex import detect_vertex_ai, vertex_env_for_runtime
from agentspec.runner.isolation import (
    IsolationBackend,
    build_bwrap_argv,
    find_bwrap,
    policy_from_trust,
    select_backend,
)
from agentspec.runner.provisioner import provision

log = logging.getLogger(__name__)


# Runtime → command builder
def build_command(plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None) -> list[str]:
    """Build the CLI command for the resolved runtime."""
    builders = {
        "claude-code": _build_claude_cmd,
        "gemini-cli": _build_gemini_cmd,
        "cursor-cli": _build_cursor_cmd,
        "codex-cli": _build_codex_cmd,
        "opencode": _build_opencode_cmd,
        "goose": _build_goose_cmd,
        "aider": _build_aider_cmd,
        "ollama": _build_ollama_cmd,
    }

    builder = builders.get(plan.runtime)
    if not builder:
        raise NotImplementedError(f"Runner not implemented for: {plan.runtime}")

    return builder(plan, manifest, input_text)


def execute(
    plan: ResolvedPlan,
    manifest: AgentManifest,
    input_text: str | None = None,
    workdir: Path | None = None,
    *,
    emit_record: bool = True,
    via: str | None = None,
    unsafe_no_isolation: bool = False,
) -> int:
    """Execute the agent by spawning the resolved runtime.

    Provisions instruction files and MCP configs into *workdir* before
    spawning. When *emit_record* is True (the default), writes a signed
    or unsigned execution record under
    ``{workdir}/.agentspec/records/<run-id>.json`` describing what ran.

    Isolation:

    - ``via=None`` / ``"auto"`` auto-detects bubblewrap on PATH. If
      present, the subprocess is wrapped in bwrap with a policy derived
      from ``manifest.trust``. If absent, a manifest with non-trivial
      trust raises; a fully permissive manifest runs unsandboxed with
      a warning (matches the v0.4.x behaviour).
    - ``via="bwrap"`` requires bwrap and fails fast if missing.
    - ``via="none"`` explicitly skips isolation. With non-trivial
      trust this raises unless ``unsafe_no_isolation=True``.
    """
    workdir = workdir or Path.cwd()
    provision(plan, manifest, workdir)
    cmd = build_command(plan, manifest, input_text)
    env = build_env(plan)

    # Accumulate warnings locally and merge them into the record at the
    # end — mutating ``plan.warnings`` in-place confuses callers that
    # reuse a plan (PR #17 review).
    run_warnings: list[str] = list(plan.warnings or [])

    backend, warning = select_backend(
        manifest.trust, requested=via, allow_unsafe=unsafe_no_isolation
    )
    if warning:
        log.warning(warning)
        run_warnings.append(warning)

    if backend == IsolationBackend.BWRAP:
        bwrap_path = find_bwrap()
        if bwrap_path is None:  # defensive — select_backend should have caught this
            raise RuntimeError("bwrap backend selected but binary not found")
        policy = policy_from_trust(
            manifest.trust,
            workdir=workdir,
            extra_env_allowlist=_env_allowlist_for_plan(plan),
        )
        # Source env values from the enriched ``env`` dict (not os.environ)
        # so layered routing vars — Vertex AI in particular — reach the
        # sandboxed runtime after ``--clearenv``. PR #17 review.
        cmd = build_bwrap_argv(bwrap_path, policy, cmd, env)

    run_id = new_run_id()
    started_at = _utc_now_iso()
    start_monotonic = time.monotonic()

    result = subprocess.run(cmd, env=env, cwd=workdir)

    if emit_record:
        _write_record(
            plan=plan,
            manifest=manifest,
            workdir=workdir,
            run_id=run_id,
            started_at=started_at,
            duration_s=time.monotonic() - start_monotonic,
            exit_code=result.returncode,
            warnings=run_warnings,
        )

    return result.returncode


def _env_allowlist_for_plan(plan: ResolvedPlan) -> list[str]:
    """Pick env-var names that must cross into the sandbox for the
    chosen runtime to reach its provider.

    Keeps the allowlist plan-driven so the sandbox doesn't leak
    unrelated env vars. Extended as new runtimes / providers land.
    """
    allowlist: list[str] = []
    src = (plan.auth_source or "").lower()
    if "anthropic" in src:
        allowlist.append("ANTHROPIC_API_KEY")
    if "openai" in src:
        allowlist.append("OPENAI_API_KEY")
    if "google" in src or "gemini" in src or "vertex" in src:
        allowlist.extend(
            [
                "GOOGLE_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_APPLICATION_CREDENTIALS",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_LOCATION",
            ]
        )
    # Vertex AI routing vars — ``build_env`` layers these on top when the
    # resolver picked Vertex. Without the allowlist entries, ``--clearenv``
    # wipes them and the runtime falls back to direct-API auth inside the
    # sandbox, breaking the run with a cryptic auth error. PR #17 review.
    if "vertex" in src:
        allowlist.extend(
            [
                "CLAUDE_CODE_USE_VERTEX",
                "ANTHROPIC_VERTEX_PROJECT_ID",
                "GOOGLE_GENAI_USE_VERTEXAI",
                "VERTEX_PROJECT",
                "VERTEX_LOCATION",
                "CLOUD_ML_REGION",
            ]
        )
    return allowlist


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_record(
    *,
    plan: ResolvedPlan,
    manifest: AgentManifest,
    workdir: Path,
    run_id: str,
    started_at: str,
    duration_s: float,
    exit_code: int,
    warnings: list[str] | None = None,
) -> None:
    """Build an ExecutionRecord from the run and persist it.

    Outcome is coarse-grained: ``success`` iff exit_code == 0, else
    ``failure``. Signal-based terminations (aborted/timeout) would need
    caller-side knowledge the runner does not currently have; they can
    be added when the CLI grows ``--timeout``.

    ``warnings`` carries run-local warnings (e.g. from the isolation
    backend selector) that should be recorded even if they were never
    mutated onto the shared ``plan.warnings``. Falls back to
    ``plan.warnings`` when None so programmatic callers of
    ``_write_record`` stay source-compatible.
    """
    outcome = "success" if exit_code == 0 else "failure"
    effective_warnings = (
        list(warnings) if warnings is not None else list(plan.warnings or [])
    )
    record = ExecutionRecord(
        run_id=run_id,
        manifest_hash=agent_hash(manifest),
        started_at=started_at,
        ended_at=_utc_now_iso(),
        duration_s=round(duration_s, 3),
        runtime=plan.runtime,
        model=plan.model or None,
        exit_code=exit_code,
        outcome=outcome,
        warnings=effective_warnings,
    )
    RecordManager(workdir).write(record)


def build_env(plan: ResolvedPlan) -> dict[str, str]:
    """Build the environment for the spawned runtime.

    Inherits the current process env, then layers Vertex AI vars on top
    when the resolver picked Vertex (auth_source contains 'vertex-ai').
    """
    env = dict(os.environ)
    if "vertex-ai" in (plan.auth_source or "").lower():
        vertex = detect_vertex_ai()
        if vertex:
            env.update(vertex_env_for_runtime(plan.runtime, vertex))
    return env


def _derive_prompt(manifest: AgentManifest, input_text: str | None) -> str | None:
    """Pick the best prompt for the agent when --input was omitted.

    Precedence:
    1. Explicit ``input_text`` (passed to ``agentspec run --input``)
    2. ``SOUL.md`` content (directory-format agents carry it on ``manifest.soul``)
    3. Agent description

    Returns None only when the agent has no usable prompt at all — the caller
    decides what to do (most runtimes interpret "no prompt" as interactive mode).
    """
    if input_text:
        return input_text
    if manifest.soul:
        return manifest.soul.strip()
    if manifest.description:
        return manifest.description
    return None


def _build_claude_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Build an argv for claude-code.

    Covered flags (verified via ``claude --help`` on v2+):

    - ``--model <name>`` — model selection; accepts aliases like
      ``sonnet`` / ``opus`` or full names like ``claude-sonnet-4-6``.
      Extracted from ``plan.model`` with the provider prefix stripped.
    - ``--system-prompt <text>`` — explicit system prompt. Claude has
      a dedicated flag (unlike gemini-cli which reads GEMINI.md).
    - ``-p/--print`` — non-interactive mode.
    - ``--dangerously-skip-permissions`` — added under AGENTSPEC_GYM=1
      so autonomous runs don't hang on every tool prompt; interactive
      ``agentspec run`` keeps the default per-tool approval.
    """
    cmd = ["claude"]

    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("--dangerously-skip-permissions")

    model_name = _claude_model_name(plan.model)
    if model_name:
        cmd.extend(["--model", model_name])

    if plan.system_prompt:
        cmd.extend(["--system-prompt", plan.system_prompt])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.extend(["-p", prompt])
    return cmd


def _claude_model_name(model: str) -> str:
    """Strip a ``provider/`` prefix from a model identifier for claude-code.

    ``claude/claude-sonnet-4-6`` → ``claude-sonnet-4-6``
    ``anthropic/claude-opus-4-6`` → ``claude-opus-4-6``
    ``sonnet``                   → ``sonnet`` (alias already bare)
    ``""`` / None                → ``""`` (caller skips the flag)
    """
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_gemini_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Build an argv for gemini-cli.

    System prompt and skill instructions are provisioned to GEMINI.md
    by the provisioner before this builder runs.
    """
    cmd = ["gemini"]

    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("-y")

    model_name = _gemini_model_name(plan.model)
    if model_name:
        cmd.extend(["-m", model_name])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.extend(["-p", prompt])
    return cmd


def _gemini_model_name(model: str) -> str:
    """Strip a ``provider/`` prefix from a model identifier for gemini-cli.

    ``gemini/gemini-2.5-pro`` → ``gemini-2.5-pro``
    ``google/gemini-2.5-pro`` → ``gemini-2.5-pro``
    ``gemini-2.5-pro``        → ``gemini-2.5-pro`` (already bare)
    ``""`` / None             → ``""`` (caller skips the flag)
    """
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_codex_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke OpenAI Codex CLI non-interactively.

    System prompt and skill instructions are provisioned to AGENTS.md
    by the provisioner before this builder runs.
    """
    cmd = ["codex", "exec"]

    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("--full-auto")

    model_name = _codex_model_name(plan.model)
    if model_name:
        cmd.extend(["-m", model_name])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.append(prompt)
    return cmd


def _codex_model_name(model: str) -> str:
    """Strip a ``provider/`` prefix for codex's ``-m`` flag.

    ``openai/gpt-5`` → ``gpt-5``
    ``o3``            → ``o3`` (alias already bare)
    ``""`` / None     → ``""`` (caller skips the flag)
    """
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_goose_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke Block's goose non-interactively.

    Per https://goose-docs.ai/docs/guides/goose-cli-commands, the
    non-interactive form is:

        goose run -t "<prompt>" [--model <name>] [--system <text>]

    Distinguished features vs. the other runners:

    - ``--system <text>`` is a real flag (unlike codex/cursor/opencode
      where we have to prepend the system prompt to the user prompt).
    - ``--model <name>`` works similarly to claude/gemini; we pass the
      bare model name after stripping any ``provider/`` prefix.
    - Goose manages provider+API-key selection itself via its own
      config (``goose configure``) — our resolver doesn't need to
      inject provider-specific env vars.

    Tool access: goose uses MCP by default (built-in "developer" tools
    plus any MCP servers the user has configured). No equivalent of
    claude's ``--dangerously-skip-permissions`` is documented for the
    ``run`` subcommand; autonomous behaviour is the default.
    """
    cmd = ["goose", "run"]

    model_name = _goose_model_name(plan.model)
    if model_name:
        cmd.extend(["--model", model_name])

    if plan.system_prompt:
        cmd.extend(["--system", plan.system_prompt])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.extend(["-t", prompt])
    return cmd


def _goose_model_name(model: str) -> str:
    """Strip a ``provider/`` prefix for goose's ``--model`` flag.

    ``anthropic/claude-sonnet-4-6`` → ``claude-sonnet-4-6``
    ``goose/claude-sonnet-4-6``     → ``claude-sonnet-4-6``
    ``claude-sonnet-4-6``           → ``claude-sonnet-4-6`` (already bare)
    ``""`` / None                   → ``""`` (caller skips the flag)
    """
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_opencode_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke opencode non-interactively.

    System prompt and skill instructions are provisioned to
    .open-code/instructions.md by the provisioner before this builder runs.
    """
    cmd = ["opencode", "run"]

    if plan.model:
        opencode_model = (
            plan.model.split("/", 1)[1] if "/" in plan.model else plan.model
        )
        cmd.extend(["-m", opencode_model])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.append(prompt)
    return cmd


def _build_cursor_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke cursor-agent non-interactively.

    System prompt and skill instructions are provisioned to .cursorrules
    by the provisioner before this builder runs.
    """
    cmd = ["cursor-agent", "-p", "--output-format", "text"]

    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("--force")

    model_name = _cursor_model_name(plan.model)
    if model_name:
        cmd.extend(["--model", model_name])

    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.append(prompt)
    return cmd


def _cursor_model_name(model: str) -> str:
    """Strip a ``provider/`` prefix for cursor-agent's ``--model`` flag.

    cursor-agent uses its own short model names (``gpt-5``,
    ``sonnet-4``, ``sonnet-4-thinking``). Callers who declare
    ``claude/sonnet-4`` in their manifest get the bare ``sonnet-4``
    passed through; users who want the thinking variant declare
    ``cursor/sonnet-4-thinking`` or just ``sonnet-4-thinking``.
    """
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_aider_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke aider non-interactively.

    Verified against aider 0.86.2's ``--help`` output:

    - ``--message <text>`` / ``-m <text>`` — single-shot prompt; aider
      runs the message and exits.
    - ``--model <name>`` — model selection (bare name).
    - ``--yes-always`` — auto-approve all confirmations; added under
      AGENTSPEC_GYM=1 so unattended runs don't block on prompts.
    """
    cmd = ["aider"]

    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("--yes-always")

    if plan.model:
        model_id = plan.model.split("/", 1)[-1] if "/" in plan.model else plan.model
        cmd.extend(["--model", model_id])

    if input_text:
        cmd.extend(["--message", input_text])
    return cmd


def _build_ollama_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    model_id = plan.model.split("/", 1)[-1] if "/" in plan.model else plan.model
    cmd = ["ollama", "run", model_id]
    if input_text:
        cmd.append(input_text)
    return cmd
