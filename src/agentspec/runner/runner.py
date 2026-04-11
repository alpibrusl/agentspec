"""Runner — spawns the resolved runtime with the agent's configuration.

Translates a ResolvedPlan into the actual CLI invocation for the
selected runtime (claude-code, gemini-cli, codex-cli, etc.).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.resolver import ResolvedPlan


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
    """Execute the agent by spawning the resolved runtime."""
    cmd = build_command(plan, manifest, input_text)
    result = subprocess.run(cmd)
    return result.returncode


def _build_claude_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    cmd = ["claude"]
    if plan.system_prompt:
        cmd.extend(["--system-prompt", plan.system_prompt])
    if input_text:
        cmd.extend(["-p", input_text])
    return cmd


def _build_gemini_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    cmd = ["gemini"]
    if input_text:
        cmd.extend(["--prompt", input_text])
    return cmd


def _build_codex_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    cmd = ["codex"]
    if plan.system_prompt:
        # Write instructions to temp file
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        tmp.write(plan.system_prompt)
        tmp.close()
        cmd.extend(["--instructions", tmp.name])
    if input_text:
        cmd.append(input_text)
    return cmd


def _build_opencode_cmd(
    plan: ResolvedPlan, manifest: AgentManifest, input_text: str | None
) -> list[str]:
    cmd = ["opencode"]
    if input_text:
        cmd.extend(["--prompt", input_text])
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
