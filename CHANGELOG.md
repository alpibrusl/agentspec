# Changelog

All notable changes to AgentSpec will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
