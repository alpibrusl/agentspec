"""Resolver — the core value of AgentSpec.

Auto-negotiates runtime, model, tools, and auth from the local environment.
This is what none of the existing agent standards implement.

Usage::

    manifest = load_agent("researcher.agent")
    plan = resolve(manifest, verbose=True)
    print(plan.runtime, plan.model, plan.tools)
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from agentspec.parser.manifest import AgentManifest
from agentspec.resolver.merger import resolve_inheritance


@dataclass
class ResolvedPlan:
    """The output of the resolver — everything needed to run the agent."""

    runtime: str
    model: str
    tools: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    auth_source: str = ""
    system_prompt: str = ""
    warnings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime": self.runtime,
            "model": self.model,
            "tools": self.tools,
            "missing_tools": self.missing_tools,
            "auth_source": self.auth_source,
            "system_prompt_length": len(self.system_prompt),
            "warnings": self.warnings,
            "decisions": self.decisions,
        }


def resolve(manifest: AgentManifest, *, verbose: bool = False) -> ResolvedPlan:
    """Resolve an agent manifest against the current environment.

    Steps:
    1. Resolve inheritance chain (base → parent → child)
    2. Detect available runtimes in PATH
    3. Match model preference list to runtime + auth
    4. Resolve abstract skills → concrete tools
    5. Resolve concrete MCP tools
    6. Build system prompt from soul/rules/traits
    """
    manifest = resolve_inheritance(manifest)

    warnings: list[str] = []
    decisions: list[str] = []

    # Step 1: detect available runtimes
    available = _detect_runtimes()
    decisions.append(f"Detected runtimes: {[k for k, v in available.items() if v]}")

    # Step 2: match model to runtime + auth
    resolved_model, runtime, auth_source = _resolve_model(
        manifest.model, manifest.auth, available, decisions
    )
    if not resolved_model:
        raise RuntimeError(
            "No model could be resolved.\n"
            "Check: API keys in env, or install a local runtime (ollama).\n"
            f"Tried preferred: {manifest.model.preferred}\n"
            f"Fallback capability: {manifest.model.fallback}"
        )

    # Step 3: resolve abstract skills → concrete tools
    skill_tools, skill_missing = _resolve_skills(manifest.skills, decisions)

    # Step 4: resolve concrete MCP tools
    mcp_tools, mcp_missing = _resolve_mcp(manifest.tools.mcp, decisions)

    # Step 5: native tools
    native_tools = manifest.tools.native

    all_tools = skill_tools + mcp_tools + native_tools
    all_missing = skill_missing + mcp_missing

    if all_missing:
        warnings.append(f"Unavailable tools (will be skipped): {all_missing}")

    # Step 6: build system prompt
    system_prompt = _build_system_prompt(manifest)

    # Step 7: observability warnings
    if manifest.observability.cost_limit:
        decisions.append(f"Cost limit: ${manifest.observability.cost_limit}")
    if manifest.observability.step_limit != 50:
        decisions.append(f"Step limit: {manifest.observability.step_limit}")

    return ResolvedPlan(
        runtime=runtime,
        model=resolved_model,
        tools=all_tools,
        missing_tools=all_missing,
        auth_source=auth_source,
        system_prompt=system_prompt,
        warnings=warnings,
        decisions=decisions,
    )


# ── Runtime detection ──────────────────────────────────────────────────────────

RUNTIME_BINARIES = {
    "claude-code": "claude",
    "gemini-cli": "gemini",
    "cursor": "cursor",
    "codex-cli": "codex",
    "opencode": "opencode",
    "aider": "aider",
    "ollama": "ollama",
}


def _detect_runtimes() -> dict[str, bool]:
    return {name: shutil.which(binary) is not None for name, binary in RUNTIME_BINARIES.items()}


# ── Model resolution ──────────────────────────────────────────────────────────

# provider prefix → (preferred runtime, env key for API auth)
PROVIDER_MAP: dict[str, tuple[str, str | None]] = {
    "claude": ("claude-code", "ANTHROPIC_API_KEY"),
    "anthropic": ("claude-code", "ANTHROPIC_API_KEY"),
    "gemini": ("gemini-cli", "GOOGLE_API_KEY"),
    "google": ("gemini-cli", "GOOGLE_API_KEY"),
    "openai": ("codex-cli", "OPENAI_API_KEY"),
    "local": ("ollama", None),
    "ollama": ("ollama", None),
}


def _resolve_model(
    model_spec: object,
    auth_spec: object,
    available: dict[str, bool],
    decisions: list[str],
) -> tuple[str | None, str, str]:
    """Try each preferred model in order, checking runtime + auth.

    When Vertex AI is configured (GOOGLE_CLOUD_PROJECT + ADC), claude-code
    and gemini-cli route through it instead of direct provider APIs.
    """
    from agentspec.resolver.vertex import detect_vertex_ai, can_route_through_vertex

    vertex = detect_vertex_ai()
    if vertex:
        decisions.append(f"  Vertex AI detected: {vertex}")

    for preferred in model_spec.preferred:  # type: ignore[union-attr]
        provider = preferred.split("/")[0]
        if provider not in PROVIDER_MAP:
            decisions.append(f"  skip {preferred}: unknown provider '{provider}'")
            continue

        runtime_name, env_key = PROVIDER_MAP[provider]

        if not available.get(runtime_name):
            decisions.append(f"  skip {preferred}: {runtime_name} not in PATH")
            continue

        # Vertex AI path: route through GCP if available and provider supports it
        if vertex and can_route_through_vertex(provider):
            auth_source = str(vertex)
            decisions.append(
                f"  selected {preferred} via {runtime_name} (Vertex AI: {vertex.location})"
            )
            return preferred, runtime_name, auth_source

        # Direct provider API path (original behavior)
        if env_key and not os.environ.get(env_key):
            decisions.append(f"  skip {preferred}: {env_key} not set (and Vertex AI not configured)")
            continue

        auth_source = f"env.{env_key}" if env_key else "local socket"
        decisions.append(f"  selected {preferred} via {runtime_name} ({auth_source})")
        return preferred, runtime_name, auth_source

    # Try fallback capability
    fallback = model_spec.fallback  # type: ignore[union-attr]
    if fallback:
        decisions.append(f"  Trying fallback capability: {fallback}")
        defaults = _capability_defaults(fallback)
        if defaults:
            class FallbackSpec:
                preferred = defaults
                fallback = None

            return _resolve_model(FallbackSpec(), auth_spec, available, decisions)

    return None, "", ""


def _capability_defaults(capability: str) -> list[str]:
    """Default model list for each capability tier."""
    return {
        "reasoning-max": [
            "claude/claude-opus-4-6",
            "openai/o3",
            "gemini/gemini-2.5-pro",
        ],
        "reasoning-high": [
            "claude/claude-sonnet-4-6",
            "openai/o3",
            "gemini/gemini-2.5-pro",
        ],
        "reasoning-mid": [
            "claude/claude-haiku-4-5",
            "openai/gpt-4o",
            "gemini/gemini-2.0-flash",
            "local/llama3:70b",
        ],
        "reasoning-low": [
            "local/llama3:8b",
            "local/mistral:7b",
        ],
    }.get(capability, [])


# ── Skill resolution ──────────────────────────────────────────────────────────

SKILL_MAP: dict[str, list[str]] = {
    "web-search": ["brave-mcp", "serper-mcp", "tavily-mcp"],
    "code-execution": ["bash", "python-repl"],
    "file-read": ["read_file"],
    "file-write": ["write_file"],
    "cite-sources": ["zotero-mcp", "arxiv-mcp"],
    "summarize": [],  # built-in LLM capability
    "image-gen": ["dalle-mcp", "stability-mcp"],
    "data-analysis": ["python-repl", "jupyter-mcp"],
    "browser": ["playwright-mcp", "puppeteer-mcp"],
    "git": ["git"],
    "github": ["github-mcp"],
    "noether-compose": ["noether"],
    "noether-run": ["noether"],
    "noether-search": ["noether"],
    "noether-serve": ["noether"],
}


def _resolve_skills(
    skills: list[str], decisions: list[str]
) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    missing: list[str] = []
    for skill in skills:
        candidates = SKILL_MAP.get(skill)
        if candidates is None:
            # Unknown skill — pass through as-is (custom skill)
            decisions.append(f"  skill {skill}: unknown, passing through")
            resolved.append(skill)
            continue
        if not candidates:
            decisions.append(f"  skill {skill}: built-in (no tool needed)")
            continue
        found = next(
            (c for c in candidates if shutil.which(c.replace("-mcp", "").replace("_", ""))),
            None,
        )
        if found:
            resolved.append(found)
            decisions.append(f"  skill {skill}: resolved to {found}")
        else:
            missing.append(skill)
            decisions.append(f"  skill {skill}: no tool found from {candidates}")
    return resolved, missing


# ── MCP tool resolution ───────────────────────────────────────────────────────


def _resolve_mcp(
    mcp_tools: list[str | dict[str, object]], decisions: list[str]
) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    missing: list[str] = []
    for tool in mcp_tools:
        name = tool if isinstance(tool, str) else next(iter(tool.keys()))
        # MCP tools are registered at runtime — we pass them through
        resolved.append(f"mcp:{name}")
        decisions.append(f"  mcp tool {name}: registered (runtime will verify)")
    return resolved, missing


# ── System prompt builder ─────────────────────────────────────────────────────

TRAIT_PROMPTS: dict[str, str] = {
    "cite-everything": "Always cite sources with URLs or references.",
    "flag-uncertainty": "Mark uncertain information with [UNCERTAIN].",
    "never-guess": "If you don't know something, say so. Never fabricate.",
    "ask-before-writing": "Always confirm with the user before writing or modifying files.",
    "think-step-by-step": "Break down complex problems step by step before answering.",
    "be-concise": "Be brief and direct. Avoid padding.",
    "self-review": "Review your own output for errors before presenting it.",
    "test-first": "Write tests before implementation code.",
    "noether-first": (
        "Prefer Noether compositions over writing code from scratch. "
        "Use `noether decompose` to break problems into verified stages, "
        "`noether search` to find reusable stages in the library, "
        "and `noether run` to execute compositions. "
        "Noether stages are content-addressed and type-safe — reuse over reinvention."
    ),
    "noether-verify": (
        "Always run `noether lint` on .nth files before executing them. "
        "Use `noether compile --verify` to type-check stage graphs."
    ),
}


def _build_system_prompt(manifest: AgentManifest) -> str:
    parts: list[str] = []

    # 1. SOUL.md takes highest priority (directory format)
    if manifest.soul:
        parts.append(manifest.soul.strip())

    # 2. Inline persona + traits (single-file format)
    elif manifest.behavior.persona or manifest.behavior.traits:
        if manifest.behavior.persona:
            parts.append(f"You are a {manifest.behavior.persona}.")
        for trait in manifest.behavior.traits:
            if trait in TRAIT_PROMPTS:
                parts.append(TRAIT_PROMPTS[trait])
            else:
                parts.append(trait)  # pass through unknown traits verbatim

    # 3. system_override as final escape hatch
    elif manifest.behavior.system_override:
        parts.append(manifest.behavior.system_override.strip())

    # 4. RULES.md always appended if present
    if manifest.rules:
        parts.append("\n## Hard Rules\n" + manifest.rules.strip())

    return "\n\n".join(parts)
