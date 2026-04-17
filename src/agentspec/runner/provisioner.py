"""Provisioner — writes runtime-specific config files before spawning a CLI.

Materialises the agent manifest's tools, skills, soul, and rules into the
config files each CLI natively reads:

- Instruction files: CLAUDE.md, GEMINI.md, .cursorrules, AGENTS.md, etc.
- MCP config files: .mcp.json, .cursor/mcp.json, .gemini/settings.json, etc.
- Folder scaffolding: .cursor/, .gemini/, .open-code/, etc.

``provision()`` writes config files (always, offline-safe).
``provision_install()`` calls CLI commands to register MCP servers and
installs declared dependencies (optional, needs binaries on PATH).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agentspec.parser.manifest import (
    AgentManifest,
    DependencySpec,
    McpServerSpec,
    SkillSpec,
)
from agentspec.resolver.resolver import ResolvedPlan, TRAIT_PROMPTS

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────


def provision(
    plan: ResolvedPlan,
    manifest: AgentManifest,
    workdir: Path,
) -> None:
    """Write runtime-specific config files into *workdir* before CLI spawn."""
    _scaffold_dirs(plan.runtime, workdir)
    _write_instruction_file(plan, manifest, workdir)
    _write_mcp_config(plan.runtime, manifest, workdir)


def provision_install(
    plan: ResolvedPlan,
    manifest: AgentManifest,
    workdir: Path,
) -> list[str]:
    """Register MCP servers via CLI commands and install declared deps.

    Returns a list of human-readable notes about what was done.
    Call after ``provision()`` for the full setup.
    """
    notes: list[str] = []

    for entry in manifest.tools.mcp:
        mcp_spec = normalize_mcp_entry(entry)
        _install_mcp_deps(mcp_spec, notes)
        _register_mcp_via_cli(plan.runtime, mcp_spec, workdir, notes)

    for skill_entry in manifest.skills:
        skill_spec = normalize_skill_entry(skill_entry)
        if skill_spec.requires != DependencySpec():
            _install_deps(skill_spec.requires, skill_spec.name, notes)

    return notes


# ── Skill normalisation ───────────────────────────────────────────────────────


def normalize_skill_entry(entry: str | dict[str, Any]) -> SkillSpec:
    """Normalise a manifest skill entry into a SkillSpec.

    Skills can be plain strings or dicts with ``name`` + ``requires``.
    """
    if isinstance(entry, str):
        well_known = WELL_KNOWN_SKILL_DEPS.get(entry)
        if well_known:
            return SkillSpec(name=entry, requires=well_known)
        return SkillSpec(name=entry)

    name = entry.get("name", next(iter(entry)))
    requires_raw = entry.get("requires", {})
    requires = DependencySpec(**requires_raw) if requires_raw else DependencySpec()
    base_requires = WELL_KNOWN_SKILL_DEPS.get(name, DependencySpec())
    merged = _merge_deps(base_requires, requires)
    return SkillSpec(name=name, requires=merged)


def skill_name(entry: str | dict[str, Any]) -> str:
    """Extract the skill name from a plain string or dict entry."""
    if isinstance(entry, str):
        return entry
    return entry.get("name", next(iter(entry)))


# ── Folder scaffolding ────────────────────────────────────────────────────────

RUNTIME_DIRS: dict[str, list[str]] = {
    "claude-code": [".claude"],
    "cursor-cli": [".cursor"],
    "gemini-cli": [".gemini"],
    "codex-cli": [],
    "opencode": [".open-code"],
    "goose": [],
    "aider": [],
    "ollama": [],
}


def _scaffold_dirs(runtime: str, workdir: Path) -> None:
    for dirname in RUNTIME_DIRS.get(runtime, []):
        (workdir / dirname).mkdir(parents=True, exist_ok=True)


# ── Instruction files ─────────────────────────────────────────────────────────

INSTRUCTION_FILES: dict[str, str | None] = {
    "claude-code": "CLAUDE.md",
    "gemini-cli": "GEMINI.md",
    "cursor-cli": ".cursorrules",
    "codex-cli": "AGENTS.md",
    "opencode": ".open-code/instructions.md",
    "aider": ".aider.conf.yml",
    "goose": None,
    "ollama": None,
}

SKILL_INSTRUCTIONS: dict[str, str] = {
    "web-search": "Search before implementing. Cite sources with URLs.",
    "code-execution": "Execute code to verify results. Handle errors gracefully.",
    "cite-sources": "Always cite sources with author, title, and URL or DOI.",
    "file-read": "Read files before modifying them.",
    "file-write": "Write files atomically. Back up before overwriting.",
    "summarize": "Be concise. Lead with the conclusion.",
    "image-gen": "Specify exact dimensions and style in prompts.",
    "data-analysis": (
        "Validate data before analysis. Handle missing values. "
        "Use .copy() to avoid SettingWithCopyWarning."
    ),
    "browser": "Wait for page loads. Handle navigation errors.",
    "git": "Frequent commits with descriptive messages. Never commit secrets.",
    "github": "Clear PR descriptions. Conventional commits. Focused PRs.",
    "noether-compose": "Use reusable stages. Search existing library before creating new ones.",
    "noether-run": "Verify compositions with `noether lint` before running.",
    "noether-search": "Search before building. Prefer verified stages.",
    "noether-serve": "Set resource limits. Monitor health endpoints.",
    "python-development": (
        "Python 3.11+. Type hints on all public functions. "
        "Use pathlib, dataclasses."
    ),
    "rust-development": (
        "Idiomatic Rust. Result types for errors. "
        "Run cargo fmt and clippy."
    ),
    "typescript-development": "Strict TypeScript. Prefer interfaces. Use async/await.",
    "pytest-testing": (
        "Use parametrize and fixtures. Cover edge cases. "
        "Aim for >80% coverage."
    ),
    "jest-testing": (
        "describe/it blocks. Mock external deps. "
        "Test success and error paths."
    ),
    "docker-management": (
        "Multi-stage builds. Pin versions. Don't run as root. "
        "Use .dockerignore."
    ),
    "kubernetes-management": (
        "Set resource limits. Add readiness/liveness probes. "
        "Use ConfigMaps/Secrets."
    ),
    "rest-api-development": (
        "FastAPI with Pydantic models. OpenAPI spec. "
        "Include /health endpoint."
    ),
    "sql-database": (
        "Parameterized queries (never f-strings for SQL). "
        "Connection pooling. Migrations."
    ),
}


def _build_instruction_content(plan: ResolvedPlan, manifest: AgentManifest) -> str:
    parts: list[str] = []

    if manifest.soul:
        parts.append(manifest.soul.strip())
    elif manifest.behavior.persona or manifest.behavior.traits:
        if manifest.behavior.persona:
            parts.append(f"You are a {manifest.behavior.persona}.")
        for trait in manifest.behavior.traits:
            if trait in TRAIT_PROMPTS:
                parts.append(TRAIT_PROMPTS[trait])
            else:
                parts.append(trait)
    elif manifest.behavior.system_override:
        parts.append(manifest.behavior.system_override.strip())

    if manifest.rules:
        parts.append("\n## Hard Rules\n" + manifest.rules.strip())

    skill_parts: list[str] = []
    for entry in manifest.skills:
        name = skill_name(entry)
        instruction = SKILL_INSTRUCTIONS.get(name)
        if instruction:
            skill_parts.append(f"### {name}\n{instruction}")
    if skill_parts:
        parts.append("\n## Skill Instructions\n" + "\n\n".join(skill_parts))

    return "\n\n".join(parts)


def _write_instruction_file(
    plan: ResolvedPlan,
    manifest: AgentManifest,
    workdir: Path,
) -> None:
    filename = INSTRUCTION_FILES.get(plan.runtime)
    if not filename:
        return

    content = _build_instruction_content(plan, manifest)
    if not content:
        return

    if plan.runtime == "aider":
        _write_aider_config(content, workdir)
        return

    target = workdir / filename
    if target.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _write_aider_config(instructions: str, workdir: Path) -> None:
    target = workdir / ".aider.conf.yml"
    if target.exists():
        return

    import yaml

    config = {
        "auto-commits": True,
        "yes": False,
        "conventions": instructions,
    }
    target.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")


# ── MCP config files ─────────────────────────────────────────────────────────

MCP_CONFIG_FILES: dict[str, str | None] = {
    "claude-code": ".mcp.json",
    "cursor-cli": ".cursor/mcp.json",
    "gemini-cli": ".gemini/settings.json",
    "codex-cli": "codex.json",
    "opencode": ".open-code/mcp.json",
    "goose": None,
    "aider": None,
    "ollama": None,
}

WELL_KNOWN_MCP_SERVERS: dict[str, McpServerSpec] = {
    "github": McpServerSpec(
        name="github",
        url="https://github.mcp.claude.com/mcp",
        transport="http",
    ),
    "postgres": McpServerSpec(
        name="postgres",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        requires=DependencySpec(npm=["@modelcontextprotocol/server-postgres"]),
    ),
    "postgresql": McpServerSpec(
        name="postgres",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        requires=DependencySpec(npm=["@modelcontextprotocol/server-postgres"]),
    ),
    "slack": McpServerSpec(
        name="slack",
        transport="stdio",
        command="npx",
        args=["-y", "@anthropic-ai/mcp-slack"],
        env={"SLACK_TOKEN": "${SLACK_TOKEN}"},
        requires=DependencySpec(
            npm=["@anthropic-ai/mcp-slack"],
            env={"SLACK_TOKEN": "Slack bot token"},
        ),
    ),
    "filesystem": McpServerSpec(
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"],
        requires=DependencySpec(npm=["@modelcontextprotocol/server-filesystem"]),
    ),
    "brave-search": McpServerSpec(
        name="brave-search",
        transport="stdio",
        command="npx",
        args=["-y", "@anthropic-ai/mcp-brave-search"],
        env={"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
        requires=DependencySpec(
            npm=["@anthropic-ai/mcp-brave-search"],
            env={"BRAVE_API_KEY": "Brave Search API key"},
        ),
    ),
    "google-scholar": McpServerSpec(
        name="google-scholar",
        transport="stdio",
        command="npx",
        args=["-y", "mcp-google-scholar"],
        requires=DependencySpec(npm=["mcp-google-scholar"]),
    ),
    "arxiv": McpServerSpec(
        name="arxiv",
        transport="stdio",
        command="npx",
        args=["-y", "mcp-arxiv"],
        requires=DependencySpec(npm=["mcp-arxiv"]),
    ),
    "jira": McpServerSpec(
        name="jira",
        transport="stdio",
        command="npx",
        args=["-y", "@anthropic-ai/mcp-jira"],
        env={
            "JIRA_URL": "${JIRA_URL}",
            "JIRA_EMAIL": "${JIRA_EMAIL}",
            "JIRA_API_TOKEN": "${JIRA_API_TOKEN}",
        },
        requires=DependencySpec(
            npm=["@anthropic-ai/mcp-jira"],
            env={
                "JIRA_URL": "Jira instance URL",
                "JIRA_EMAIL": "Jira user email",
                "JIRA_API_TOKEN": "Jira API token",
            },
        ),
    ),
    "playwright": McpServerSpec(
        name="playwright",
        transport="stdio",
        command="npx",
        args=["-y", "@anthropic-ai/mcp-playwright"],
        requires=DependencySpec(
            npm=["@anthropic-ai/mcp-playwright"],
            setup=["npx playwright install chromium"],
        ),
    ),
    "puppeteer": McpServerSpec(
        name="puppeteer",
        transport="stdio",
        command="npx",
        args=["-y", "@anthropic-ai/mcp-puppeteer"],
        requires=DependencySpec(npm=["@anthropic-ai/mcp-puppeteer"]),
    ),
    "noether": McpServerSpec(
        name="noether",
        transport="stdio",
        command="noether",
        args=["mcp", "serve"],
        requires=DependencySpec(pip=["caloron-noether"]),
    ),
}

WELL_KNOWN_SKILL_DEPS: dict[str, DependencySpec] = {
    "python-development": DependencySpec(nix=["python311"]),
    "rust-development": DependencySpec(nix=["cargo", "rustc"]),
    "typescript-development": DependencySpec(nix=["nodejs"]),
    "data-analysis": DependencySpec(pip=["pandas", "numpy"]),
    "pytest-testing": DependencySpec(pip=["pytest", "pytest-cov"]),
    "jest-testing": DependencySpec(npm=["jest"]),
    "docker-management": DependencySpec(nix=["docker"]),
    "kubernetes-management": DependencySpec(nix=["kubectl"]),
    "browser": DependencySpec(
        npm=["playwright"],
        setup=["npx playwright install chromium"],
    ),
}


def normalize_mcp_entry(entry: str | dict[str, Any]) -> McpServerSpec:
    """Normalise a manifest MCP entry into a structured spec.

    Handles three forms:
    1. Plain string: ``"github"`` → well-known lookup
    2. Dict with ``name`` key: ``{name: "x", url: "...", ...}`` → direct spec
    3. Legacy dict: ``{"postgres": {"connection": "..."}}`` → name from key
    """
    if isinstance(entry, str):
        if entry in WELL_KNOWN_MCP_SERVERS:
            return WELL_KNOWN_MCP_SERVERS[entry]
        return McpServerSpec(name=entry)

    if "name" in entry:
        name = entry["name"]
        base = WELL_KNOWN_MCP_SERVERS.get(name, McpServerSpec(name=name))
        return base.model_copy(
            update={k: v for k, v in entry.items() if k != "name" and v}
        )

    name = next(iter(entry))
    config = entry[name]
    base = WELL_KNOWN_MCP_SERVERS.get(name, McpServerSpec(name=name))
    if isinstance(config, dict):
        return base.model_copy(
            update={k: v for k, v in config.items() if v}
        )
    return base


def _server_to_mcp_json(spec: McpServerSpec) -> dict[str, Any]:
    if spec.transport == "http" and spec.url:
        return {
            "type": "http",
            "url": spec.url,
            **({"headers": spec.headers} if spec.headers else {}),
        }

    if spec.command:
        result: dict[str, Any] = {
            "command": spec.command,
            "args": list(spec.args),
        }
        if spec.env:
            result["env"] = dict(spec.env)
        return result

    if spec.url:
        return {
            "command": "npx",
            "args": ["-y", "mcp-remote", spec.url],
            **({"env": dict(spec.env)} if spec.env else {}),
        }

    return {"command": spec.name, "args": [], "env": dict(spec.env)}


def _write_mcp_config(runtime: str, manifest: AgentManifest, workdir: Path) -> None:
    config_file = MCP_CONFIG_FILES.get(runtime)
    if not config_file:
        return

    mcp_entries = manifest.tools.mcp
    if not mcp_entries:
        return

    servers: dict[str, Any] = {}
    for entry in mcp_entries:
        spec = normalize_mcp_entry(entry)
        servers[spec.name] = _server_to_mcp_json(spec)

    if not servers:
        return

    target = workdir / config_file
    if target.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    config = {"mcpServers": servers}
    target.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )


# ── CLI-native MCP registration ──────────────────────────────────────────────

MCP_CLI_COMMANDS: dict[str, str] = {
    "claude-code": "claude",
    "gemini-cli": "gemini",
    "codex-cli": "codex",
    "cursor-cli": "cursor",
}


def _register_mcp_via_cli(
    runtime: str,
    spec: McpServerSpec,
    workdir: Path,
    notes: list[str],
) -> None:
    binary = MCP_CLI_COMMANDS.get(runtime)
    if not binary or not shutil.which(binary):
        return

    try:
        if runtime == "claude-code":
            _register_claude_mcp(binary, spec, workdir)
        elif runtime == "gemini-cli":
            _register_gemini_mcp(binary, spec, workdir)
        elif runtime == "codex-cli":
            _register_codex_mcp(binary, spec)
        elif runtime == "cursor-cli":
            _register_cursor_mcp(binary, spec, workdir)
        notes.append(f"registered MCP server '{spec.name}' via {binary}")
    except (subprocess.CalledProcessError, OSError) as exc:
        log.warning("CLI MCP registration failed for %s: %s", spec.name, exc)
        notes.append(f"CLI registration failed for '{spec.name}' (config file used as fallback)")


def _register_claude_mcp(binary: str, spec: McpServerSpec, workdir: Path) -> None:
    cmd = [binary, "mcp", "add", "--scope=project"]
    if spec.transport == "http" and spec.url:
        cmd.extend(["--transport", "http", spec.name, spec.url])
    elif spec.command:
        cmd.extend([spec.name, spec.command, *spec.args])
    else:
        return
    subprocess.run(cmd, cwd=workdir, check=True, capture_output=True, timeout=30)


def _register_gemini_mcp(binary: str, spec: McpServerSpec, workdir: Path) -> None:
    cmd = [binary, "mcp", "add", "--scope=project"]
    if spec.transport == "http" and spec.url:
        cmd.extend(["--transport", "http", spec.name, spec.url])
    elif spec.command:
        cmd.extend([spec.name, spec.command, *spec.args])
    else:
        return
    subprocess.run(cmd, cwd=workdir, check=True, capture_output=True, timeout=30)


def _register_codex_mcp(binary: str, spec: McpServerSpec) -> None:
    cmd = [binary, "mcp", "add"]
    if spec.url:
        cmd.extend(["--url", spec.url, spec.name])
    elif spec.command:
        cmd.extend([spec.name, spec.command, *spec.args])
    else:
        return
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)


def _register_cursor_mcp(binary: str, spec: McpServerSpec, workdir: Path) -> None:
    mcp_json = {spec.name: _server_to_mcp_json(spec)}
    cmd = [binary, "--add-mcp", json.dumps(mcp_json), "--mcp-workspace", str(workdir)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)


# ── Dependency installation ───────────────────────────────────────────────────


def _install_mcp_deps(spec: McpServerSpec, notes: list[str]) -> None:
    if spec.requires == DependencySpec():
        return
    _install_deps(spec.requires, f"mcp:{spec.name}", notes)


def _install_deps(deps: DependencySpec, label: str, notes: list[str]) -> None:
    if deps.pip:
        _run_install(["pip", "install", "--quiet", *deps.pip], label, "pip", notes)
    if deps.npm:
        _run_install(["npm", "install", "--save-dev", *deps.npm], label, "npm", notes)
    if deps.cargo:
        for pkg in deps.cargo:
            _run_install(["cargo", "install", pkg], label, "cargo", notes)
    for cmd_str in deps.setup:
        _run_install(cmd_str.split(), label, "setup", notes)


def _run_install(
    cmd: list[str], label: str, kind: str, notes: list[str]
) -> None:
    binary = cmd[0]
    if not shutil.which(binary):
        notes.append(f"skip {kind} install for {label}: {binary} not in PATH")
        return
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        notes.append(f"installed {kind} deps for {label}")
    except (subprocess.CalledProcessError, OSError) as exc:
        log.warning("install failed for %s (%s): %s", label, kind, exc)
        notes.append(f"{kind} install failed for {label}: {exc}")


def _merge_deps(base: DependencySpec, override: DependencySpec) -> DependencySpec:
    return DependencySpec(
        pip=list(dict.fromkeys(base.pip + override.pip)),
        npm=list(dict.fromkeys(base.npm + override.npm)),
        cargo=list(dict.fromkeys(base.cargo + override.cargo)),
        nix=list(dict.fromkeys(base.nix + override.nix)),
        setup=list(dict.fromkeys(base.setup + override.setup)),
        env={**base.env, **override.env},
    )
