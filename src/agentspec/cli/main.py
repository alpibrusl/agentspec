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
import os
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
    via: str = typer.Option(
        "",
        "--via",
        help="Isolation backend: auto|bwrap|none. Defaults to auto (use bwrap if installed). Reads AGENTSPEC_ISOLATION env if unset. type:string",
    ),
    unsafe_no_isolation: bool = typer.Option(
        False,
        "--unsafe-no-isolation",
        help="Acknowledge running a tight-trust manifest without a sandbox. Required with --via=none on non-permissive manifests. type:bool",
    ),
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
    resolved_via = via or os.environ.get("AGENTSPEC_ISOLATION") or None
    try:
        returncode = execute(
            plan,
            manifest,
            input_text,
            via=resolved_via,
            unsafe_no_isolation=unsafe_no_isolation,
        )
    except RuntimeError as exc:
        raise PreconditionError(
            str(exc),
            hint="Install bubblewrap, pass --via=none --unsafe-no-isolation, or relax the manifest's trust block",
        ) from exc
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
        ("Push to local registry", "agentspec push researcher.agent"),
        ("Push to remote registry", "agentspec push researcher.agent --registry http://localhost:3000"),
        ("JSON output", "agentspec push researcher.agent --output json"),
    ],
    idempotent=True,
    see_also=["pull", "search", "validate"],
)
def push(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    registry: str = typer.Option(
        "", "--registry", "-r",
        help="Remote registry URL (e.g. http://localhost:3000). Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Publish an agent to a registry (local or remote Noether registry)."""
    start = time.time()

    path = Path(agent_path)
    if not path.exists():
        raise NotFoundError(f"Agent not found: {agent_path}")

    manifest = load_agent(path)
    h = agent_hash(manifest)

    # Determine registry: CLI flag > env var > local fallback
    registry_url = registry or os.environ.get("AGENTSPEC_REGISTRY") or os.environ.get("NOETHER_REGISTRY", "")

    if registry_url:
        # Remote push via Noether registry
        from agentspec.registry.client import push_agent
        result = push_agent(manifest, registry_url)
        if "error" in result:
            raise PreconditionError(
                f"Registry push failed: {result['error']}",
                hint=f"Check registry is running at {registry_url}",
            )
        data = {
            "hash": result["hash"],
            "registry_id": result.get("registry_id", ""),
            "registry": registry_url,
            "name": manifest.name,
            "version": manifest.version,
        }
    else:
        # Local push (filesystem)
        registry_dir = Path("registry/agents")
        registry_dir.mkdir(parents=True, exist_ok=True)
        agent_file = registry_dir / f"{h.replace(':', '_')}.json"
        agent_file.write_text(manifest.model_dump_json(indent=2))

        index_path = Path("registry/index.json")
        index: dict[str, object] = {}
        if index_path.exists():
            index = json.loads(index_path.read_text())
        index[h] = {"name": manifest.name, "version": manifest.version, "tags": manifest.tags}
        index_path.write_text(json.dumps(index, indent=2))

        data = {"hash": h, "name": manifest.name, "version": manifest.version, "registry": "local"}

    if output == OutputFormat.json:
        emit(success_envelope("push", data, version="0.1.0", start_time=start), output)
    else:
        dest = registry_url or "local"
        sys.stdout.write(f"Pushed: {manifest.name}@{manifest.version} -> {h} ({dest})\n")


# ── pull ──────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Pull from local registry", "agentspec pull ag1:abc123def456"),
        ("Pull from remote registry", "agentspec pull abc123def456 --registry http://localhost:3000"),
        ("JSON output", "agentspec pull ag1:abc123 --output json"),
    ],
    idempotent=True,
    see_also=["push", "search"],
)
def pull(
    ref: str = typer.Argument(help="Agent reference: registry stage ID or ag1:<hash>. type:string"),
    registry: str = typer.Option(
        "", "--registry", "-r",
        help="Remote registry URL. Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Pull an agent from a registry (local or remote Noether registry)."""
    start = time.time()

    registry_url = registry or os.environ.get("AGENTSPEC_REGISTRY") or os.environ.get("NOETHER_REGISTRY", "")

    if registry_url:
        # Remote pull via Noether registry
        from agentspec.registry.client import pull_agent
        manifest = pull_agent(ref, registry_url)
        if not manifest:
            raise NotFoundError(
                f"Agent not found in registry: {ref}",
                hint=f"Try: agentspec search <query> --registry {registry_url}",
            )
    else:
        # Local pull (filesystem)
        registry_file = Path("registry/agents") / f"{ref.replace(':', '_')}.json"
        if not registry_file.exists():
            raise NotFoundError(
                f"Agent not found in local registry: {ref}",
                hint="Try: agentspec push <agent> first, or use --registry for remote",
            )
        manifest = AgentManifest.model_validate_json(registry_file.read_text())

    out_file = f"{manifest.name}.agent"

    import yaml
    data_dict = manifest.model_dump(exclude_none=True, exclude_defaults=True)
    data_dict.pop("_source_dir", None)
    Path(out_file).write_text(yaml.dump(data_dict, default_flow_style=False, sort_keys=False))

    data = {"name": manifest.name, "version": manifest.version, "output": out_file}
    if output == OutputFormat.json:
        emit(success_envelope("pull", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"Pulled: {manifest.name}@{manifest.version} -> {out_file}\n")


# ── search ────────────────────────────────────────────────────────────────────


@app.command()
@acli_command(
    examples=[
        ("Search for researcher agents", "agentspec search researcher --registry http://localhost:3000"),
        ("JSON output", "agentspec search coder --registry http://localhost:3000 --output json"),
    ],
    idempotent=True,
    see_also=["push", "pull"],
)
def search(
    query: str = typer.Argument(help="Search query. type:string"),
    registry: str = typer.Option(
        "", "--registry", "-r",
        help="Registry URL. Also reads AGENTSPEC_REGISTRY / NOETHER_REGISTRY env. type:string",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Search for agents in a remote Noether registry."""
    start = time.time()

    registry_url = registry or os.environ.get("AGENTSPEC_REGISTRY") or os.environ.get("NOETHER_REGISTRY", "")
    if not registry_url:
        raise PreconditionError(
            "No registry URL configured",
            hint="Set AGENTSPEC_REGISTRY or NOETHER_REGISTRY env var, or pass --registry URL",
        )

    from agentspec.registry.client import search_agents
    results = search_agents(query, registry_url)

    data = {"query": query, "count": len(results), "agents": results}
    if output == OutputFormat.json:
        emit(success_envelope("search", data, version="0.1.0", start_time=start), output)
    else:
        if not results:
            sys.stdout.write(f"No agents found for: {query}\n")
        else:
            sys.stdout.write(f"Found {len(results)} agent(s):\n")
            for r in results:
                sys.stdout.write(f"  {r['id'][:12]}  {r['name']}\n")
                if r.get("description"):
                    sys.stdout.write(f"    {r['description'][:80]}\n")


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


# ── gym ───────────────────────────────────────────────────────────────────────

gym_app = typer.Typer(help="Tune and test agents against task fixtures in isolation")
app.add_typer(gym_app, name="gym")


@gym_app.command("run")
def gym_run(
    agent_path: str = typer.Argument(help="Path to .agent file or directory. type:path"),
    task_path: str = typer.Argument(
        "", help="Path to a task YAML fixture (omit when using --corpus). type:path"
    ),
    corpus: str = typer.Option(
        "", "--corpus", help="Run every *.yaml task under this directory. type:path"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Skip agent execution; only score assertions. type:bool"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Run an agent spec against a task fixture (or a whole corpus) and print the score."""
    from agentspec.gym import load_task, run_corpus, run_task
    from agentspec.gym.runner import result_to_json

    start = time.time()

    if not Path(agent_path).exists():
        raise NotFoundError(f"Agent not found: {agent_path}")
    if not corpus and not task_path:
        raise InvalidArgsError("Provide either a task path or --corpus <dir>")
    if corpus and task_path:
        raise InvalidArgsError("Use either a task path OR --corpus, not both")

    if corpus:
        if not Path(corpus).is_dir():
            raise NotFoundError(f"Corpus not found: {corpus}")
        summary = run_corpus(agent_path, corpus, dry_run=dry_run)
        if output == OutputFormat.json:
            emit(
                success_envelope(
                    "gym.run", summary.to_dict(), version="0.1.0", start_time=start
                ),
                output,
            )
            return
        sys.stdout.write(
            f"Corpus:  {corpus} ({summary.total_tasks} task(s))\n"
            f"Result:  {summary.fully_passed}/{summary.total_tasks} tasks fully passed "
            f"({summary.task_pass_rate:.0%}); "
            f"{summary.passed_assertions}/{summary.total_assertions} assertions "
            f"({summary.assertion_pass_rate:.0%}) in {summary.duration_s:.2f}s\n\n"
        )
        for r in summary.results:
            mark = "PASS" if r.failed == 0 and r.passed > 0 else "FAIL"
            sys.stdout.write(
                f"  [{mark}] {r.task_id:<30} {r.passed}/{r.passed + r.failed} "
                f"({r.duration_s:.1f}s)\n"
            )
        if summary.fully_passed < summary.total_tasks:
            raise SystemExit(1)
        return

    if not Path(task_path).exists():
        raise NotFoundError(f"Task not found: {task_path}")

    task = load_task(task_path)
    result = run_task(agent_path, task, dry_run=dry_run)

    if output == OutputFormat.json:
        emit(
            success_envelope(
                "gym.run",
                json.loads(result_to_json(result)),
                version="0.1.0",
                start_time=start,
            ),
            output,
        )
        return

    sys.stdout.write(f"Task:    {result.task_id}\n")
    sys.stdout.write(f"Agent:   {result.agent_hash}\n")
    sys.stdout.write(
        f"Result:  {result.passed}/{result.passed + result.failed} assertions passed "
        f"({result.pass_rate:.0%}) in {result.duration_s}s\n"
    )
    if result.dry_run:
        sys.stdout.write("Mode:    dry-run (agent not executed)\n")
    if result.command:
        sys.stdout.write(f"Command: {' '.join(result.command)}\n")
    sys.stdout.write("\n")
    for a in result.assertions:
        mark = "PASS" if a["passed"] else "FAIL"
        sys.stdout.write(f"  [{mark}] {a['type']}")
        if a["detail"]:
            sys.stdout.write(f" — {a['detail']}")
        sys.stdout.write("\n")
    if result.stderr_tail:
        sys.stdout.write(f"\nstderr: {result.stderr_tail[-200:]}\n")

    if result.failed:
        raise SystemExit(1)


# ── records ───────────────────────────────────────────────────────────────────

records_app = typer.Typer(help="Inspect and verify execution records written by agentspec run")
app.add_typer(records_app, name="records")


@records_app.command("list")
def records_list(
    manifest_hash: str = typer.Option(
        "", "--agent", help="Filter by manifest hash (ag1:…). type:string"
    ),
    workdir: str = typer.Option(
        ".", "--workdir", "-C", help="Workspace root. type:path"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """List execution records under ``{workdir}/.agentspec/records/`` newest first."""
    from agentspec.records.manager import RecordManager

    start = time.time()
    mgr = RecordManager(workdir)
    records = mgr.list(manifest_hash=manifest_hash or None)

    data = {
        "count": len(records),
        "records": [r.model_dump(by_alias=True, exclude_none=True) for r in records],
    }
    if output == OutputFormat.json:
        emit(success_envelope("records.list", data, version="0.1.0", start_time=start), output)
        return

    if not records:
        sys.stdout.write("No records.\n")
        return
    for r in records:
        mark = "ok" if r.outcome == "success" else r.outcome
        sys.stdout.write(
            f"  {r.run_id}  {r.started_at}  {r.runtime:<12}  exit={r.exit_code}  [{mark}]\n"
        )


@records_app.command("show")
def records_show(
    run_id: str = typer.Argument(help="Run ID (ULID). type:string"),
    workdir: str = typer.Option(
        ".", "--workdir", "-C", help="Workspace root. type:path"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Print a single execution record in detail."""
    from agentspec.records.manager import RecordManager

    start = time.time()
    mgr = RecordManager(workdir)
    try:
        record = mgr.load(run_id)
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc), hint="Try: agentspec records list") from exc

    data = record.model_dump(by_alias=True, exclude_none=True)
    if output == OutputFormat.json:
        emit(success_envelope("records.show", data, version="0.1.0", start_time=start), output)
        return

    for k, v in data.items():
        sys.stdout.write(f"  {k:<16} {v}\n")


@records_app.command("verify")
def records_verify(
    run_id: str = typer.Argument(help="Run ID (ULID). type:string"),
    pubkey: str = typer.Option(
        ..., "--pubkey", help="Ed25519 public key (hex). type:string"
    ),
    workdir: str = typer.Option(
        ".", "--workdir", "-C", help="Workspace root. type:path"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.text, "--output", help="Output format. type:enum[text|json|table]"
    ),
) -> None:
    """Verify a signed execution record against a public key.

    Exits non-zero when verification fails — so CI scripts can gate on it.
    """
    from agentspec.records.manager import RecordManager

    start = time.time()
    mgr = RecordManager(workdir)
    valid = mgr.verify(run_id, pubkey)

    data = {"run_id": run_id, "valid": valid}
    if output == OutputFormat.json:
        emit(success_envelope("records.verify", data, version="0.1.0", start_time=start), output)
    else:
        sys.stdout.write(f"{'OK' if valid else 'INVALID'}  {run_id}\n")

    if not valid:
        raise SystemExit(1)


# ── Entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    app.run()
