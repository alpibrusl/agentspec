# Changelog

All notable changes to AgentSpec will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-04-16

Runner + resolver parity sweep across all four supported coding CLIs
(claude-code, gemini-cli, cursor-cli, opencode), triggered by a field
report that gemini-cli calls were failing despite credentials being set.
Applying the same rigor to all four surfaced a real bug per CLI.

### Added

- **`cursor-cli` runtime is now actually runnable.** The resolver table
  had `"cursor" → "cursor"` but the real binary is `cursor-agent`, and
  the runner dispatcher had no builder entry at all — `build_command`
  raised `NotImplementedError` on the cursor path. Fixed the binary,
  renamed the runtime key to `cursor-cli` (matches caloron-noether's
  naming + every other `-cli` entry), and added `_build_cursor_cmd`
  producing `cursor-agent -p <prompt> --output-format text` with the
  system prompt prepended.
- **`--model` flag threading on claude-code and gemini-cli.** Both
  CLIs accept a model override flag (`--model` / `-m`) but the runner
  never passed it. Manifests' `model.preferred` was effectively
  ignored — both CLIs ran with whatever their own default was.
  `_claude_model_name()` and `_gemini_model_name()` strip the
  `provider/` prefix (`claude/claude-sonnet-4-6` → `claude-sonnet-4-6`;
  `gemini/gemini-2.5-pro` → `gemini-2.5-pro`; aliases like `sonnet`
  pass through unchanged).
- **Gemini-cli autonomous mode.** Gym runs now pass `-y` (yolo) under
  `AGENTSPEC_GYM=1`, matching the `--dangerously-skip-permissions`
  treatment claude-code was already getting. Without this, gemini
  hung every tool-approval prompt and stalled the subprocess.
- **Gemini-cli system prompts.** gemini-cli has no `--system-prompt`
  flag; it reads `GEMINI.md` from the CWD as system instructions.
  Runner now writes `plan.system_prompt` to that file when present,
  with a guard against stomping an existing `GEMINI.md` that belongs
  to the user's project.

### Fixed

- **`GEMINI_API_KEY` is now primary for gemini, not `GOOGLE_API_KEY`.**
  gemini-cli itself only reads `GEMINI_API_KEY` (verified via its own
  auth-error message listing the accepted env vars). Users who set
  only `GOOGLE_API_KEY` would pass our resolver then fail at runtime
  with "please set an Auth method". `PROVIDER_MAP["gemini"]` is now a
  tuple `(GEMINI_API_KEY, GOOGLE_API_KEY)` — any one set counts;
  `GOOGLE_API_KEY` stays as a historical fallback for users who set
  the Google-branded key. Resolver decision log names whichever key
  satisfied the check.
- **`opencode --print` → `opencode run`.** The runner built
  `opencode --print <prompt>` but the real non-interactive form per
  https://opencode.ai/docs/cli/ (and caloron-noether's field-validated
  FRAMEWORKS table) is the `run` subcommand. Modern opencode rejects
  `--print` with "unknown flag".
- **Opencode Vertex AI region goes to the right variable.**
  `vertex_env_for_runtime("opencode")` set `GOOGLE_CLOUD_LOCATION`
  (what gemini-cli reads) but opencode actually reads `VERTEX_LOCATION`
  per its google-vertex-ai provider docs. Symptom: opencode silently
  defaulted to the `global` region regardless of what the resolver
  picked; for EU-residency users (default `europe-west1`) every Vertex
  request went to the wrong region. Now injects both — opencode reads
  `VERTEX_LOCATION`, gemini-cli keeps reading `GOOGLE_CLOUD_LOCATION`.
- **Gym runner now threads the Vertex AI env to spawned CLIs.**
  Gym's `run_task` was doing `env = os.environ.copy()` and bypassing
  `build_env(plan)`, which is what injects the Vertex-specific env
  vars when the resolver picks that auth path. Result: even when a
  user had GCP + ADC set up correctly and the resolver reported
  `auth_source="vertex-ai …"`, the subprocess inherited
  `GOOGLE_CLOUD_PROJECT` (from os.environ) but not
  `GOOGLE_GENAI_USE_VERTEXAI=true`, so gemini-cli fell back to
  direct-API mode and failed. Fixed by returning
  `(argv, env, note)` from `_resolve_command` and layering
  `AGENTSPEC_GYM=1` on top of `build_env(plan)` instead of
  `os.environ.copy()`.
- **Stale `__version__` in `__init__.py`.** Was `0.1.0` while
  `pyproject.toml` was `0.2.2`. Both now at `0.3.0`.

### Changed (possibly breaking — minor surface)

- `PROVIDER_MAP` values changed from `tuple[str, str | None]` to
  `tuple[str, tuple[str, ...] | None]` so multiple accepted env keys
  can be listed. Internal API; not imported from the public
  `agentspec` namespace, but callers that depended on the old shape
  will need to adapt.
- Runtime key `"cursor"` renamed to `"cursor-cli"`. Affects the
  resolver's runtime-identifier surface and `RUNTIME_BINARIES`; no
  manifest-facing change (the provider prefix in
  `model.preferred` was never `cursor/...`).

### Tests

- 111 → 139 green (1 skipped is a deliberate unreachable-path test).
- New: 15 gemini-cli tests + 5 Vertex-integration tests +
  28 multi-CLI parity tests (including a meta-test that catches
  "binary added to `RUNTIME_BINARIES` but no builder in the
  dispatcher" — the exact regression that cursor-cli had before).

### Live-validation caveats (deliberate, flagged in commits)

- claude-code and gemini-cli fixes are validated against the real
  installed CLIs' `--help` output.
- cursor-agent and opencode aren't installed on the dev box used to
  ship this release; their fixes are validated against (a) official
  docs and (b) caloron-noether's field-tested `FRAMEWORKS` values.
  Next field opportunity is to run `agentspec gym run <agent> <task>`
  with each against a small fixture.

## [0.2.2] — 2026-04-13

### Fixed

- **Resolver: `opencode/default` and `aider/default` no longer fall through as
  unknown providers.** Both runtimes manage their own auth/model selection —
  the resolver now recognises them as valid providers that need only binary
  presence in PATH, not API keys.
- **Runner: `agentspec run <dir>` no longer crashes claude-code with
  "Input must be provided either through stdin or as a prompt argument".**
  When `--input` is omitted, the runner now derives a prompt from the agent's
  `SOUL.md` (for directory-format agents) or `description` field. Same fallback
  applies to gemini-cli and codex-cli.
- **Runner: opencode invocation updated to `opencode --print "<prompt>"`** —
  the non-interactive mode — instead of the previous `--prompt` flag. System
  prompts are prepended to the user prompt so opencode (which picks its own
  model) still sees the agent's persona and traits.

Reported by an integrator building the `llm-wiki` pipeline. Thanks.

### Added

- New helper `agentspec.runner.runner._derive_prompt` — single source of truth
  for the input/SOUL.md/description fallback chain. Used by all non-ollama
  runners.
- 12 regression tests in `tests/test_issue_opencode_and_fallback.py`.

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
