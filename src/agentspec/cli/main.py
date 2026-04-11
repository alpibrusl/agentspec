"""ACLI-compliant CLI for AgentSpec.

Uses the acli-spec SDK so agents can discover capabilities via
``agentspec introspect`` and ``agentspec --help``.

Commands:
- run       — resolve and execute an agent
- validate  — validate a .agent file against the schema
- resolve   — show what would run without executing
- extend    — scaffold a child agent from an existing one
- push      — publish an agent to the registry
- pull      — fetch an agent from the registry
- schema    — print the JSON Schema for .agent files
- init      — scaffold a new .agent project
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer

from acli import (
    ACLIApp,
    OutputFormat,
    acli_command,
    emit,
    emit_progress,
    error_envelope,
    success_envelope,
    NotFoundError,
    InvalidArgsError,
    PreconditionError,
)

from agentspec.parser.loader import load_agent, agent_hash, export_schema
from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.resolver import resolve, ResolvedPlan
from agentspec.runner.runner import execute, build_command

app = ACLIApp(
    name="agentspec",
    version="0.1.0",
    help="Universal agent manifest standard — resolve and run .agent files",
)


# ── run ───────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Run a researcher agent", "agentspec run researcher.agent"),
        ("Run with input", "agentspec run researcher.agent --input 'quantum tunneling'"),
        ("Dry-run to see the plan", "agentspec run researcher.agent --dry-run"),
        ("Verbose resolver output", "agentspec run researcher.agent --verbose"),
    ],
    idempotent=False,
    see_also=["resolve", "validate"],
)
def run(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    input_: str = typer.Option("", "--input", "-i", help="Input to pass to the agent. type:string"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show resolver decisions. type:bool"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Resolve without executing. type:bool"),
) -> None:
    """Resolve and run an agent from a .agent file or directory."""
    start = time.time()

    path = Path(agent_path)
    if not path.exists():
        raise NotFoundError(
            f"Agent not found: {agent_path}",
            hint=f"Check the path exists. Try: ls {path.parent}",
        )

    manifest = load_agent(path)

    if output == OutputFormat.json:
        emit_progress("resolve", "running", detail=f"Resolving {manifest.name}")

    try:
        plan = resolve(manifest, verbose=verbose)
    except RuntimeError as exc:
        raise PreconditionError(
            str(exc),
            hint="Install a runtime (claude, gemini, codex, ollama) or set API keys",
        ) from exc

    if dry_run:
        data = {
            "agent": manifest.name,
            "version": manifest.version,
            **plan.to_dict(),
        }
        if output == OutputFormat.json:
            emit(success_envelope("run", data, version="0.1.0", start_time=start, dry_run=True), output)
        else:
            _print_plan_text(plan, verbose)
            sys.stdout.write("\nDry run complete.\n")
        return

    if output == OutputFormat.json:
        data = {"agent": manifest.name, **plan.to_dict()}
        emit(success_envelope("run", data, version="0.1.0", start_time=start), output)
    else:
        _print_plan_text(plan, verbose)
        sys.stdout.write(f"\nLaunching {plan.runtime}...\n")

    input_text = input_ if input_ else None
    returncode = execute(plan, manifest, input_text)
    raise SystemExit(returncode)


# ── validate ──────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Validate a single file", "agentspec validate researcher.agent"),
        ("Validate a directory agent", "agentspec validate ./researcher/"),
        ("JSON output", "agentspec validate researcher.agent --output json"),
    ],
    idempotent=True,
    see_also=["resolve", "schema"],
)
def validate(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Validate a .agent file or directory against the schema."""
    start = time.time()

    path = Path(agent_path)
    if not path.exists():
        raise NotFoundError(f"Agent not found: {agent_path}")

    try:
        manifest = load_agent(path)
    except Exception as exc:
        raise InvalidArgsError(
            f"Invalid agent manifest: {exc}",
            hint="Check YAML syntax and required fields (name, apiVersion)",
        ) from exc

    h = agent_hash(manifest)
    data = {
        "valid": True,
        "name": manifest.name,
        "version": manifest.version,
        "apiVersion": manifest.apiVersion,
        "hash": h,
        "skills": manifest.skills,
        "has_base": manifest.base is not None,
        "has_soul": manifest.soul is not None,
        "has_rules": manifest.rules is not None,
    }

    if output == OutputFormat.json:
        emit(success_envelope("validate", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Valid: {manifest.name}@{manifest.version} ({h})\n")
        if manifest.base:
            sys.stdout.write(f"  base: {manifest.base}\n")
        if manifest.skills:
            sys.stdout.write(f"  skills: {', '.join(manifest.skills)}\n")
        if manifest.soul:
            sys.stdout.write("  SOUL.md: present\n")
        if manifest.rules:
            sys.stdout.write("  RULES.md: present\n")


# ── resolve ───────────────────────────────────────────────────────────────────


@app.command(name="resolve")
@acli_command(
    examples=[
        ("Show resolver plan", "agentspec resolve researcher.agent"),
        ("JSON output", "agentspec resolve researcher.agent --output json"),
    ],
    idempotent=True,
    see_also=["run", "validate"],
)
def resolve_cmd(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Show what would run without executing. Always verbose."""
    start = time.time()

    path = Path(agent_path)
    if not path.exists():
        raise NotFoundError(f"Agent not found: {agent_path}")

    manifest = load_agent(path)

    try:
        plan = resolve(manifest, verbose=True)
    except RuntimeError as exc:
        raise PreconditionError(
            str(exc),
            hint="Install a runtime or set API keys",
        ) from exc

    data = {"agent": manifest.name, "version": manifest.version, **plan.to_dict()}

    if output == OutputFormat.json:
        emit(success_envelope("resolve", data, version="0.1.0", start_time=start), output)
    else:
        _print_plan_text(plan, verbose=True)


# ── extend ────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Extend a researcher", "agentspec extend researcher.agent"),
        ("Custom output file", "agentspec extend researcher.agent --out legal-researcher.agent"),
    ],
    idempotent=False,
    see_also=["validate", "init"],
)
def extend(
    base_path: str = typer.Argument(help="Base agent to extend. type:path"),
    out: str = typer.Option("extended.agent", "--out", "-o", help="Output file path. type:path"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Scaffold a new agent that extends an existing one."""
    start = time.time()

    path = Path(base_path)
    if not path.exists():
        raise NotFoundError(f"Base agent not found: {base_path}")

    manifest = load_agent(path)

    scaffold = f"""apiVersion: agent/v1
name: my-{manifest.name}
version: 0.1.0
description: "Extended from {manifest.name}"

base: {base_path}

merge:
  skills: append
  tools: append
  behavior: override
  trust: restrict

# Add your overrides below:
# model:
#   capability: reasoning-high
#   preferred:
#     - claude/claude-sonnet-4-6
#
# skills:
#   - web-search
#
# behavior:
#   traits:
#     - cite-everything
#
# trust:
#   filesystem: read-only
"""
    Path(out).write_text(scaffold)

    data = {"output": out, "base": manifest.name, "base_version": manifest.version}
    if output == OutputFormat.json:
        emit(success_envelope("extend", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Scaffolded: {out} (extends {manifest.name}@{manifest.version})\n")


# ── push ──────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Push an agent", "agentspec push researcher.agent"),
        ("JSON output", "agentspec push researcher.agent --output json"),
    ],
    idempotent=True,
    see_also=["pull", "validate"],
)
def push(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Publish an agent to the local registry."""
    start = time.time()

    path = Path(agent_path)
    if not path.exists():
        raise NotFoundError(f"Agent not found: {agent_path}")

    manifest = load_agent(path)
    h = agent_hash(manifest)

    # Write to local registry
    registry_dir = Path("registry/agents")
    registry_dir.mkdir(parents=True, exist_ok=True)
    agent_file = registry_dir / f"{h.replace(':', '_')}.json"
    agent_file.write_text(manifest.model_dump_json(indent=2))

    # Update index
    index_path = Path("registry/index.json")
    index: dict[str, object] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text())
    index[h] = {
        "name": manifest.name,
        "version": manifest.version,
        "tags": manifest.tags,
    }
    index_path.write_text(json.dumps(index, indent=2))

    data = {"hash": h, "name": manifest.name, "version": manifest.version}
    if output == OutputFormat.json:
        emit(success_envelope("push", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Pushed: {manifest.name}@{manifest.version} -> {h}\n")


# ── pull ──────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Pull by hash", "agentspec pull ag1:abc123def456"),
        ("JSON output", "agentspec pull ag1:abc123def456 --output json"),
    ],
    idempotent=True,
    see_also=["push"],
)
def pull(
    ref: str = typer.Argument(help="Agent reference: ag1:<hash> or name@version. type:string"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Pull an agent from the local registry."""
    start = time.time()

    registry_file = Path("registry/agents") / f"{ref.replace(':', '_')}.json"
    if not registry_file.exists():
        raise NotFoundError(
            f"Agent not found in registry: {ref}",
            hint="Try: agentspec push <agent> first, or check registry/index.json",
        )

    manifest = AgentManifest.model_validate_json(registry_file.read_text())
    out_file = f"{manifest.name}.agent"

    # Export as YAML
    import yaml
    data_dict = manifest.model_dump(exclude_none=True, exclude_defaults=True)
    Path(out_file).write_text(yaml.dump(data_dict, default_flow_style=False, sort_keys=False))

    data = {"name": manifest.name, "version": manifest.version, "output": out_file}
    if output == OutputFormat.json:
        emit(success_envelope("pull", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Pulled: {manifest.name}@{manifest.version} -> {out_file}\n")


# ── schema ────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Print JSON Schema", "agentspec schema"),
        ("Save to file", "agentspec schema --out agent-v1.json"),
    ],
    idempotent=True,
    see_also=["validate"],
)
def schema(
    out: str = typer.Option("", "--out", "-o", help="Write schema to file. type:path"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Print the JSON Schema for .agent files."""
    start = time.time()
    schema_data = export_schema()

    if out:
        Path(out).write_text(json.dumps(schema_data, indent=2))
        if output == OutputFormat.json:
            emit(success_envelope("schema", {"path": out}, version="0.1.0", start_time=start), output)
        else:
            sys.stdout.write(f"Schema written to {out}\n")
    else:
        if output == OutputFormat.json:
            emit(success_envelope("schema", schema_data, version="0.1.0", start_time=start), output)
        else:
            sys.stdout.write(json.dumps(schema_data, indent=2) + "\n")


# ── init ──────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Create a new agent", "agentspec init my-agent"),
        ("Create directory format", "agentspec init my-agent --format directory"),
    ],
    idempotent=False,
    see_also=["extend", "validate"],
)
def init(
    name: str = typer.Argument(help="Agent name. type:string"),
    format_: str = typer.Option("file", "--format", "-f", help="Format: file or directory. type:enum[file|directory]"),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Scaffold a new .agent project."""
    start = time.time()

    if format_ == "directory":
        _init_directory(name)
        result_path = f"{name}/"
    else:
        _init_file(name)
        result_path = f"{name}.agent"

    data = {"name": name, "format": format_, "path": result_path}
    if output == OutputFormat.json:
        emit(success_envelope("init", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Created: {result_path}\n")


def _init_file(name: str) -> None:
    content = f"""apiVersion: agent/v1
name: {name}
version: 0.1.0
description: "{name} agent"

model:
  capability: reasoning-mid
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b

skills:
  - code-execution
  - file-read
  - file-write

behavior:
  persona: {name}
  traits:
    - think-step-by-step
    - be-concise
  temperature: 0.3
  max_steps: 20

trust:
  filesystem: scoped
  scope: [./workspace]
  network: none
  exec: sandboxed

observability:
  trace: true
  step_limit: 30
"""
    Path(f"{name}.agent").write_text(content)


def _init_directory(name: str) -> None:
    d = Path(name)
    d.mkdir(parents=True, exist_ok=True)

    (d / "agent.yaml").write_text(f"""apiVersion: agent/v1
name: {name}
version: 0.1.0

model:
  capability: reasoning-mid
  preferred:
    - claude/claude-sonnet-4-6
    - gemini/gemini-2.5-pro
    - local/llama3:70b

skills:
  - code-execution
  - file-read
  - file-write

trust:
  filesystem: scoped
  scope: [./workspace]
  network: none
  exec: sandboxed

observability:
  trace: true
  step_limit: 30
""")

    (d / "SOUL.md").write_text(f"""# {name.replace('-', ' ').title()}

## Identity
You are a helpful agent.

## Communication Style
- Clear and direct
- Show your reasoning
- Ask before taking irreversible actions
""")

    (d / "RULES.md").write_text("""# Hard Rules

## Must Never
- Write outside the designated workspace
- Execute commands without user approval
- Fabricate information

## Must Always
- Cite sources for factual claims
- Ask before destructive operations
""")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_plan_text(plan: ResolvedPlan, verbose: bool = False) -> None:
    sys.stdout.write(f"  Runtime:  {plan.runtime}\n")
    sys.stdout.write(f"  Model:    {plan.model}\n")
    sys.stdout.write(f"  Auth:     {plan.auth_source}\n")
    sys.stdout.write(f"  Tools:    {', '.join(plan.tools) or 'none'}\n")
    if plan.missing_tools:
        sys.stdout.write(f"  Missing:  {', '.join(plan.missing_tools)}\n")
    for w in plan.warnings:
        sys.stdout.write(f"  Warning:  {w}\n")
    if verbose and plan.decisions:
        sys.stdout.write("\n  Resolver decisions:\n")
        for d in plan.decisions:
            sys.stdout.write(f"    {d}\n")


# ── Entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    app.run()
