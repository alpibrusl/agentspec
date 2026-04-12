# Changelog

All notable changes to AgentSpec will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-04-12

### Added

- **Vertex AI backend support** (`agentspec.resolver.vertex`). When
  `GOOGLE_CLOUD_PROJECT` is set and Application Default Credentials are
  available, the resolver routes claude-code, gemini-cli, aider, and
  opencode through Vertex AI instead of direct provider APIs. Default
  region: `europe-west1` (EU data residency).
- New env vars: `AGENTSPEC_VERTEX_PROJECT`, `AGENTSPEC_VERTEX_LOCATION`
  (override the standard `GOOGLE_CLOUD_*` if needed).
- Per-runtime env injection in the runner: `CLAUDE_CODE_USE_VERTEX=1`
  for claude-code, `GOOGLE_GENAI_USE_VERTEXAI=true` for gemini-cli,
  `VERTEX_PROJECT/LOCATION` for aider, base GCP env for opencode.
- 21 new tests (`tests/test_vertex.py`) covering detection, routing,
  per-runtime env, and runner env injection.

### Notes

- codex-cli (OpenAI) cannot route through Vertex AI — OpenAI models are
  not on Vertex Model Garden. Continues to use OpenAI direct API.
- Vertex AI takes precedence over direct API keys when both are
  configured for a routable provider (claude/anthropic, gemini/google).

## [0.1.0] — 2026-04-12

Initial public release.

### Added

- **Parser** — Pydantic models for the `.agent` schema, single-file and directory format support, content-addressable hashing (`ag1:` prefix).
- **Resolver** — auto-negotiates runtime, model, tools, and auth from the local environment. Supports 6 LLM runtimes: `claude-code`, `gemini-cli`, `codex-cli`, `aider`, `opencode`, `ollama`.
- **Inheritance & merger** — `base:` chain with explicit merge strategies (`append`, `override`, `restrict`). Hardcoded trust-restrict invariant: child agents can never escalate parent permissions.
- **Profile system** — persistent agent identity that accumulates across sprints. Memories, portfolio (CV), skill proofs. Cold-start seeding from manifest.
- **Signing** — Ed25519 (via PyNaCl) for memories, portfolio entries, and skill proofs. HMAC-SHA256 fallback when PyNaCl is not installed.
- **CLI** — ACLI-compliant: `init`, `validate`, `resolve`, `run`, `extend`, `push`, `pull`, `search`, `schema`. Plus `introspect`, `version`, `skill` from acli-spec.
- **Registry client** — push, pull, and semantic search against any Noether-compatible registry (e.g. `noether-cloud`).
- **Noether integration** — 9 AgentSpec operations registered as Noether stages (validate, resolve, hash, merge, evolve, schema, profile_create, profile_retro, profile_export).
- **Base templates** — `bases/{claude,gemini,codex,local}.agent` plus `-noether` variants for each.
- **Documentation** — full MkDocs Material site at <https://alpibrusl.github.io/agentspec/>.
- **45 tests** across parser, merger, and resolver.

[0.1.0]: https://github.com/alpibrusl/agentspec/releases/tag/v0.1.0
