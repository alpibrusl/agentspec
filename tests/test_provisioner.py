"""Tests for the provisioner — runtime-specific config file generation.

Covers:
- Instruction file generation per runtime (CLAUDE.md, GEMINI.md, etc.)
- MCP config file generation per runtime (.mcp.json, .cursor/mcp.json, etc.)
- Well-known MCP server expansion
- Backward compat with string and legacy dict MCP entries
- Skill instruction injection
- No-overwrite guard for existing files
- Folder scaffolding per runtime
- DependencySpec and enriched skills
- CLI-native MCP registration
- provision_install()
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentspec.parser.manifest import (
    AgentManifest,
    BehaviorSpec,
    DependencySpec,
    McpServerSpec,
    ModelSpec,
    SkillSpec,
    ToolsSpec,
)
from agentspec.resolver.resolver import ResolvedPlan
from agentspec.runner.provisioner import (
    INSTRUCTION_FILES,
    MCP_CONFIG_FILES,
    RUNTIME_DIRS,
    SKILL_INSTRUCTIONS,
    WELL_KNOWN_MCP_SERVERS,
    WELL_KNOWN_SKILL_DEPS,
    normalize_mcp_entry,
    normalize_skill_entry,
    provision,
    provision_install,
    skill_name,
)


def _plan(runtime: str = "claude-code", **kw) -> ResolvedPlan:
    defaults = dict(runtime=runtime, model="claude/claude-sonnet-4-6")
    defaults.update(kw)
    return ResolvedPlan(**defaults)


def _manifest(**kw) -> AgentManifest:
    defaults = dict(name="test-agent", version="0.1.0")
    defaults.update(kw)
    return AgentManifest(**defaults)


# ── Instruction files ─────────────────────────────────────────────────────────


class TestInstructionFiles:
    def test_claude_md_from_persona(self, tmp_path: Path):
        manifest = _manifest(behavior=BehaviorSpec(persona="code reviewer"))
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "code reviewer" in content

    def test_gemini_md_from_soul(self, tmp_path: Path):
        manifest = _manifest(soul="# Deep Researcher\nYou cite everything.")
        provision(_plan("gemini-cli"), manifest, tmp_path)
        content = (tmp_path / "GEMINI.md").read_text()
        assert "Deep Researcher" in content
        assert "cite everything" in content

    def test_cursorrules_from_traits(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(traits=["cite-everything", "be-concise"])
        )
        provision(_plan("cursor-cli"), manifest, tmp_path)
        content = (tmp_path / ".cursorrules").read_text()
        assert "cite" in content.lower()
        assert "concise" in content.lower() or "brief" in content.lower()

    def test_agents_md_for_codex(self, tmp_path: Path):
        manifest = _manifest(behavior=BehaviorSpec(persona="auditor"))
        provision(_plan("codex-cli"), manifest, tmp_path)
        assert (tmp_path / "AGENTS.md").exists()
        assert "auditor" in (tmp_path / "AGENTS.md").read_text()

    def test_opencode_instructions(self, tmp_path: Path):
        manifest = _manifest(behavior=BehaviorSpec(persona="helper"))
        provision(_plan("opencode"), manifest, tmp_path)
        target = tmp_path / ".open-code" / "instructions.md"
        assert target.exists()
        assert "helper" in target.read_text()

    def test_goose_no_instruction_file(self, tmp_path: Path):
        manifest = _manifest(behavior=BehaviorSpec(persona="builder"))
        provision(_plan("goose"), manifest, tmp_path)
        assert not list(tmp_path.glob("*.md"))

    def test_ollama_no_instruction_file(self, tmp_path: Path):
        manifest = _manifest(behavior=BehaviorSpec(persona="builder"))
        provision(_plan("ollama"), manifest, tmp_path)
        assert not list(tmp_path.glob("*.md"))

    def test_no_overwrite_existing(self, tmp_path: Path):
        existing = "# My project instructions"
        (tmp_path / "CLAUDE.md").write_text(existing)
        manifest = _manifest(behavior=BehaviorSpec(persona="new persona"))
        provision(_plan("claude-code"), manifest, tmp_path)
        assert (tmp_path / "CLAUDE.md").read_text() == existing

    def test_no_file_when_no_content(self, tmp_path: Path):
        manifest = _manifest()
        provision(_plan("claude-code"), manifest, tmp_path)
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_rules_appended(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(persona="researcher"),
            rules="Never fabricate citations.",
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Hard Rules" in content
        assert "Never fabricate" in content

    def test_system_override(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(system_override="Custom system prompt here.")
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Custom system prompt" in content

    def test_soul_takes_priority_over_persona(self, tmp_path: Path):
        manifest = _manifest(
            soul="# SOUL content",
            behavior=BehaviorSpec(persona="ignored persona"),
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "SOUL content" in content
        assert "ignored persona" not in content


# ── Skill instructions ────────────────────────────────────────────────────────


class TestSkillInstructions:
    def test_skill_instructions_injected(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(persona="dev"),
            skills=["web-search", "git"],
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "### web-search" in content
        assert "### git" in content
        assert "Search before" in content
        assert "commit secrets" in content

    def test_unknown_skill_not_in_instructions(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(persona="dev"),
            skills=["custom-skill-xyz"],
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "custom-skill-xyz" not in content

    def test_all_instruction_file_runtimes_covered(self):
        for runtime, filename in INSTRUCTION_FILES.items():
            assert runtime in (
                "claude-code", "gemini-cli", "cursor-cli", "codex-cli",
                "opencode", "aider", "goose", "ollama",
            ), f"Unknown runtime {runtime} in INSTRUCTION_FILES"


# ── MCP config files ─────────────────────────────────────────────────────────


class TestMcpConfig:
    def test_claude_mcp_json_from_well_known(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("claude-code"), manifest, tmp_path)
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "github" in config["mcpServers"]
        server = config["mcpServers"]["github"]
        assert server["type"] == "http"
        assert "github" in server["url"]

    def test_cursor_mcp_json(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["postgres"]))
        provision(_plan("cursor-cli"), manifest, tmp_path)
        target = tmp_path / ".cursor" / "mcp.json"
        assert target.exists()
        config = json.loads(target.read_text())
        assert "postgres" in config["mcpServers"]

    def test_gemini_settings_json(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("gemini-cli"), manifest, tmp_path)
        target = tmp_path / ".gemini" / "settings.json"
        assert target.exists()
        config = json.loads(target.read_text())
        assert "github" in config["mcpServers"]

    def test_codex_json(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["slack"]))
        provision(_plan("codex-cli"), manifest, tmp_path)
        config = json.loads((tmp_path / "codex.json").read_text())
        assert "slack" in config["mcpServers"]
        assert "SLACK_TOKEN" in config["mcpServers"]["slack"].get("env", {})

    def test_opencode_mcp_json(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("opencode"), manifest, tmp_path)
        target = tmp_path / ".open-code" / "mcp.json"
        assert target.exists()

    def test_no_mcp_config_for_aider(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("aider"), manifest, tmp_path)
        assert not (tmp_path / ".mcp.json").exists()

    def test_no_mcp_config_for_goose(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("goose"), manifest, tmp_path)
        assert not list(tmp_path.glob("*.json"))

    def test_no_mcp_config_when_no_mcp_tools(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=[], native=["bash"]))
        provision(_plan("claude-code"), manifest, tmp_path)
        assert not (tmp_path / ".mcp.json").exists()

    def test_no_overwrite_existing_mcp_config(self, tmp_path: Path):
        existing = '{"mcpServers": {"custom": {}}}'
        (tmp_path / ".mcp.json").write_text(existing)
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan("claude-code"), manifest, tmp_path)
        assert json.loads((tmp_path / ".mcp.json").read_text()) == json.loads(existing)

    def test_multiple_mcp_servers(self, tmp_path: Path):
        manifest = _manifest(
            tools=ToolsSpec(mcp=["github", "postgres", "slack"])
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert len(config["mcpServers"]) == 3
        assert "github" in config["mcpServers"]
        assert "postgres" in config["mcpServers"]
        assert "slack" in config["mcpServers"]


# ── normalize_mcp_entry ──────────────────────────────────────────────────────


class TestNormalizeMcpEntry:
    def test_string_well_known(self):
        spec = normalize_mcp_entry("github")
        assert spec.name == "github"
        assert spec.url == "https://github.mcp.claude.com/mcp"
        assert spec.transport == "http"

    def test_string_unknown(self):
        spec = normalize_mcp_entry("my-custom-server")
        assert spec.name == "my-custom-server"
        assert spec.url is None

    def test_dict_with_name_key(self):
        spec = normalize_mcp_entry({
            "name": "my-db",
            "command": "npx",
            "args": ["-y", "server-postgres", "postgresql://localhost/db"],
            "transport": "stdio",
        })
        assert spec.name == "my-db"
        assert spec.command == "npx"
        assert spec.transport == "stdio"

    def test_dict_with_name_key_merges_well_known(self):
        spec = normalize_mcp_entry({
            "name": "github",
            "headers": {"Authorization": "Bearer token123"},
        })
        assert spec.name == "github"
        assert spec.url == "https://github.mcp.claude.com/mcp"
        assert spec.headers["Authorization"] == "Bearer token123"

    def test_legacy_dict_format(self):
        spec = normalize_mcp_entry({"postgres": {"connection": "env.DB_URL"}})
        assert spec.name == "postgres"
        assert spec.command == "npx"

    def test_legacy_dict_unknown_server(self):
        spec = normalize_mcp_entry({"custom": {"url": "https://example.com"}})
        assert spec.name == "custom"
        assert spec.url == "https://example.com"


# ── Well-known registry ──────────────────────────────────────────────────────


class TestWellKnownRegistry:
    def test_all_entries_have_valid_transport(self):
        for name, spec in WELL_KNOWN_MCP_SERVERS.items():
            assert spec.transport in ("stdio", "http", "sse"), (
                f"{name} has invalid transport: {spec.transport}"
            )

    def test_stdio_servers_have_command(self):
        for name, spec in WELL_KNOWN_MCP_SERVERS.items():
            if spec.transport == "stdio":
                assert spec.command, f"{name} is stdio but has no command"

    def test_http_servers_have_url(self):
        for name, spec in WELL_KNOWN_MCP_SERVERS.items():
            if spec.transport == "http":
                assert spec.url, f"{name} is http but has no url"

    def test_postgres_and_postgresql_are_aliases(self):
        assert WELL_KNOWN_MCP_SERVERS["postgres"].name == "postgres"
        assert WELL_KNOWN_MCP_SERVERS["postgresql"].name == "postgres"


# ── End-to-end provisioning ──────────────────────────────────────────────────


class TestEndToEnd:
    def test_full_provision_claude(self, tmp_path: Path):
        manifest = _manifest(
            soul="# Deep Researcher\nYou are thorough.",
            rules="Never guess. Always verify.",
            skills=["web-search", "github"],
            tools=ToolsSpec(mcp=["github", "postgres"], native=["bash"]),
        )
        provision(_plan("claude-code"), manifest, tmp_path)

        claude_md = (tmp_path / "CLAUDE.md").read_text()
        assert "Deep Researcher" in claude_md
        assert "Hard Rules" in claude_md
        assert "Never guess" in claude_md
        assert "### web-search" in claude_md
        assert "### github" in claude_md

        mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "github" in mcp_config["mcpServers"]
        assert "postgres" in mcp_config["mcpServers"]

    def test_full_provision_gemini(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(persona="data analyst"),
            skills=["data-analysis"],
            tools=ToolsSpec(mcp=["github"]),
        )
        provision(_plan("gemini-cli"), manifest, tmp_path)

        gemini_md = (tmp_path / "GEMINI.md").read_text()
        assert "data analyst" in gemini_md
        assert "### data-analysis" in gemini_md

        settings = json.loads(
            (tmp_path / ".gemini" / "settings.json").read_text()
        )
        assert "github" in settings["mcpServers"]

    @pytest.mark.parametrize(
        "runtime,instruction_file",
        [
            (rt, f)
            for rt, f in INSTRUCTION_FILES.items()
            if f is not None and rt != "aider"
        ],
    )
    def test_all_runtimes_get_instruction_file(
        self, tmp_path: Path, runtime: str, instruction_file: str
    ):
        manifest = _manifest(behavior=BehaviorSpec(persona="tester"))
        provision(_plan(runtime), manifest, tmp_path)
        assert (tmp_path / instruction_file).exists()

    @pytest.mark.parametrize(
        "runtime,mcp_file",
        [
            (rt, f)
            for rt, f in MCP_CONFIG_FILES.items()
            if f is not None
        ],
    )
    def test_all_runtimes_get_mcp_config(
        self, tmp_path: Path, runtime: str, mcp_file: str
    ):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        provision(_plan(runtime), manifest, tmp_path)
        target = tmp_path / mcp_file
        assert target.exists()
        config = json.loads(target.read_text())
        assert "mcpServers" in config


# ── Folder scaffolding ────────────────────────────────────────────────────────


class TestFolderScaffolding:
    @pytest.mark.parametrize(
        "runtime,expected_dirs",
        list(RUNTIME_DIRS.items()),
    )
    def test_scaffold_creates_dirs(
        self, tmp_path: Path, runtime: str, expected_dirs: list[str]
    ):
        manifest = _manifest()
        provision(_plan(runtime), manifest, tmp_path)
        for dirname in expected_dirs:
            assert (tmp_path / dirname).is_dir(), f"{dirname} not created for {runtime}"

    def test_claude_gets_dot_claude_dir(self, tmp_path: Path):
        manifest = _manifest()
        provision(_plan("claude-code"), manifest, tmp_path)
        assert (tmp_path / ".claude").is_dir()

    def test_cursor_gets_dot_cursor_dir(self, tmp_path: Path):
        manifest = _manifest()
        provision(_plan("cursor-cli"), manifest, tmp_path)
        assert (tmp_path / ".cursor").is_dir()

    def test_gemini_gets_dot_gemini_dir(self, tmp_path: Path):
        manifest = _manifest()
        provision(_plan("gemini-cli"), manifest, tmp_path)
        assert (tmp_path / ".gemini").is_dir()

    def test_opencode_gets_dot_open_code_dir(self, tmp_path: Path):
        manifest = _manifest()
        provision(_plan("opencode"), manifest, tmp_path)
        assert (tmp_path / ".open-code").is_dir()

    def test_existing_dirs_not_clobbered(self, tmp_path: Path):
        (tmp_path / ".claude").mkdir()
        marker = tmp_path / ".claude" / "existing-file.txt"
        marker.write_text("keep me")
        manifest = _manifest()
        provision(_plan("claude-code"), manifest, tmp_path)
        assert marker.read_text() == "keep me"


# ── DependencySpec ────────────────────────────────────────────────────────────


class TestDependencySpec:
    def test_well_known_servers_have_requires(self):
        servers_with_deps = [
            "postgres", "slack", "filesystem", "brave-search",
            "playwright", "puppeteer", "noether",
        ]
        for name in servers_with_deps:
            spec = WELL_KNOWN_MCP_SERVERS[name]
            assert spec.requires != DependencySpec(), (
                f"well-known server '{name}' should have requires"
            )

    def test_github_http_has_no_npm_requires(self):
        spec = WELL_KNOWN_MCP_SERVERS["github"]
        assert spec.requires == DependencySpec()

    def test_postgres_requires_npm_package(self):
        spec = WELL_KNOWN_MCP_SERVERS["postgres"]
        assert "@modelcontextprotocol/server-postgres" in spec.requires.npm

    def test_playwright_requires_setup_command(self):
        spec = WELL_KNOWN_MCP_SERVERS["playwright"]
        assert any("chromium" in cmd for cmd in spec.requires.setup)

    def test_slack_requires_env_var(self):
        spec = WELL_KNOWN_MCP_SERVERS["slack"]
        assert "SLACK_TOKEN" in spec.requires.env


# ── Enriched skills ──────────────────────────────────────────────────────────


class TestEnrichedSkills:
    def test_skill_name_from_string(self):
        assert skill_name("web-search") == "web-search"

    def test_skill_name_from_dict(self):
        assert skill_name({"name": "python-development"}) == "python-development"

    def test_normalize_plain_string_skill(self):
        spec = normalize_skill_entry("web-search")
        assert spec.name == "web-search"
        assert spec.requires == DependencySpec()

    def test_normalize_well_known_skill_with_deps(self):
        spec = normalize_skill_entry("data-analysis")
        assert spec.name == "data-analysis"
        assert "pandas" in spec.requires.pip

    def test_normalize_enriched_skill_dict(self):
        spec = normalize_skill_entry({
            "name": "python-development",
            "requires": {"pip": ["black", "mypy"]},
        })
        assert spec.name == "python-development"
        assert "black" in spec.requires.pip
        assert "mypy" in spec.requires.pip
        assert "python311" in spec.requires.nix

    def test_normalize_unknown_enriched_skill(self):
        spec = normalize_skill_entry({
            "name": "custom-skill",
            "requires": {"pip": ["custom-lib"]},
        })
        assert spec.name == "custom-skill"
        assert "custom-lib" in spec.requires.pip

    def test_well_known_skill_deps_registry(self):
        assert "data-analysis" in WELL_KNOWN_SKILL_DEPS
        assert "pandas" in WELL_KNOWN_SKILL_DEPS["data-analysis"].pip

    def test_enriched_skills_in_manifest(self):
        manifest = _manifest(
            skills=[
                "web-search",
                {"name": "python-development", "requires": {"pip": ["black"]}},
            ],
        )
        assert len(manifest.skills) == 2

    def test_enriched_skills_in_instruction_file(self, tmp_path: Path):
        manifest = _manifest(
            behavior=BehaviorSpec(persona="dev"),
            skills=[
                "web-search",
                {"name": "python-development", "requires": {"pip": ["black"]}},
            ],
        )
        provision(_plan("claude-code"), manifest, tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "### web-search" in content
        assert "### python-development" in content


# ── provision_install ─────────────────────────────────────────────────────────


class TestProvisionInstall:
    def test_returns_notes(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        plan = _plan("claude-code")
        provision(plan, manifest, tmp_path)
        notes = provision_install(plan, manifest, tmp_path)
        assert isinstance(notes, list)

    @patch("agentspec.runner.provisioner.shutil.which", return_value=None)
    def test_skips_when_no_binary(self, mock_which, tmp_path: Path):
        manifest = _manifest(
            tools=ToolsSpec(mcp=["postgres"]),
            skills=[{"name": "data-analysis", "requires": {"pip": ["pandas"]}}],
        )
        plan = _plan("claude-code")
        provision(plan, manifest, tmp_path)
        notes = provision_install(plan, manifest, tmp_path)
        skip_notes = [n for n in notes if "skip" in n or "not in PATH" in n]
        assert len(skip_notes) > 0

    def test_no_install_for_http_servers(self, tmp_path: Path):
        manifest = _manifest(tools=ToolsSpec(mcp=["github"]))
        plan = _plan("claude-code")
        provision(plan, manifest, tmp_path)
        notes = provision_install(plan, manifest, tmp_path)
        install_notes = [n for n in notes if "installed" in n and "pip" in n]
        assert len(install_notes) == 0
