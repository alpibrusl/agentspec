"""Runner — spawns the resolved runtime with the agent's configuration.

Translates a ResolvedPlan into the actual CLI invocation for the
selected runtime (claude-code, gemini-cli, codex-cli, etc.).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.resolver.vertex import detect_vertex_ai, vertex_env_for_runtime


# Runtime → command builder
def build_command(plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None) -> list[str]:
    """Build the CLI command for the resolved runtime."""
    builders = {
        "claude-code": _build_claude_cmd,
        "gemini-cli": _build_gemini_cmd,
        "codex-cli": _build_codex_cmd,
        "opencode": _build_opencode_cmd,
        "aider": _build_aider_cmd,
        "ollama": _build_ollama_cmd,
    }

    builder = builders.get(plan.runtime)
    if not builder:
        raise NotImplementedError(f"Runner not implemented for: {plan.runtime}")

    return builder(plan, manifest, input_text)


def execute(plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None = None) -> int:
    """Execute the agent by spawning the resolved runtime.

    If Vertex AI is configured (via GCP env vars + ADC), the relevant
    backend env vars are injected so the spawned CLI talks to Vertex
    instead of the direct provider API.
    """
    cmd = build_command(plan, manifest, input_text)
    env = build_env(plan)
    result = subprocess.run(cmd, env=env)
    return result.returncode


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
    cmd = ["claude"]
    # In autonomous runners (gym, caloron sprint) the agent needs tool
    # access without interactive approval prompts. AGENTSPEC_GYM=1 opts
    # into claude's permission bypass. `agentspec run` without that env
    # keeps the default prompt-every-tool behaviour so interactive users
    # aren't silently granting full access.
    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("--dangerously-skip-permissions")
    if plan.system_prompt:
        cmd.extend(["--system-prompt", plan.system_prompt])
    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.extend(["-p", prompt])
    return cmd


def _build_gemini_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Build an argv for gemini-cli.

    Covers the flags that matter for agent-like runs:

    - ``-m/--model`` — extracted from ``plan.model`` (e.g. the provider
      prefix is stripped from ``gemini/gemini-2.5-pro`` to pass
      ``gemini-2.5-pro``).
    - ``-y/--yolo`` — added in gym/non-interactive runs so the agent
      doesn't hang on tool-approval prompts. Mirrors the claude-code
      behaviour when AGENTSPEC_GYM=1.
    - ``-p/--prompt`` — non-interactive mode with the supplied prompt.

    System prompt handling: gemini-cli has no ``--system-prompt`` flag.
    It instead reads ``GEMINI.md`` from the current working directory
    as system instructions. ``plan.system_prompt`` is written to that
    file when present. Callers who don't want the file persisted
    should run gemini in a throwaway worktree (the gym does this).
    """
    cmd = ["gemini"]

    # Autonomous mode — skip interactive approval prompts.
    if os.environ.get("AGENTSPEC_GYM") == "1":
        cmd.append("-y")

    # Model selection — strip the provider prefix so `gemini/gemini-2.5-pro`
    # becomes `gemini-2.5-pro`. Don't pass -m if resolution produced an
    # empty string (defensive: the resolver always sets plan.model, but
    # some test fixtures skip it).
    model_name = _gemini_model_name(plan.model)
    if model_name:
        cmd.extend(["-m", model_name])

    # System prompt lands at GEMINI.md in CWD. gemini-cli picks it up
    # automatically as system instructions. Only write when we have
    # something to write — don't stomp an existing GEMINI.md that
    # belongs to the user's project.
    if plan.system_prompt:
        import pathlib
        gemini_md = pathlib.Path.cwd() / "GEMINI.md"
        if not gemini_md.exists():
            gemini_md.write_text(plan.system_prompt)

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
    cmd = ["codex"]
    if plan.system_prompt:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        tmp.write(plan.system_prompt)
        tmp.close()
        cmd.extend(["--instructions", tmp.name])
    prompt = _derive_prompt(manifest, input_text)
    if prompt:
        cmd.append(prompt)
    return cmd


def _build_opencode_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    """Invoke opencode non-interactively.

    opencode's `--print` mode accepts a single positional prompt and emits the
    model's response to stdout. We prepend the resolver-built system prompt so
    opencode (which selects the model itself) still gets the agent's persona
    and traits.
    """
    cmd = ["opencode", "--print"]
    prompt = _derive_prompt(manifest, input_text) or ""
    if plan.system_prompt:
        prompt = f"{plan.system_prompt}\n\n{prompt}".strip()
    if prompt:
        cmd.append(prompt)
    return cmd


def _build_aider_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    cmd = ["aider"]
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
