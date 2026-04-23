# Changelog

All notable changes to AgentSpec will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`SKILL.md` at repo root** (agentskills.io open standard). Generated
  by `agentspec skill --out SKILL.md`; contains `name` / `description` /
  `when_to_use` frontmatter plus the full command reference. Drops
  directly into `.claude/skills/agentspec/SKILL.md`,
  `.cursor/skills/agentspec/SKILL.md`, Gemini CLI, Codex, and other
  [agentskills.io](https://agentskills.io)-compatible tools so an agent
  can bootstrap on agentspec without running `--help` first. A CI drift
  check regenerates `SKILL.md` and fails the build if it diverged from
  the committed copy — mirrors the schema drift guard.

### Changed

- **Bumped `acli-spec` pin to `>=0.5.0`** — the release adds
  `skill_description` and `skill_when_to_use` kwargs on `ACLIApp`
  (agentskills.io frontmatter) and renames the emitted file from
  `SKILLS.md` (plural) to `SKILL.md` (singular) per the open standard.
  See [acli PR #30](https://github.com/alpibrusl/acli/pull/30).

- **Resolver runtime detection now delegates to `llm-here`.** The four
  subscription CLIs shared with caloron-noether and noether-grid
  (`claude-code`, `gemini-cli`, `cursor-cli`, `opencode`) are now
  detected by calling `llm-here detect` and translating its provider
  ids back to agentspec's runtime-name key space. Runtimes unique to
  agentspec (`codex-cli`, `goose`, `aider`, `ollama`, `test-echo`)
  continue to use `shutil.which`, as does everything if `llm-here` is
  not on `PATH`. Merge is **union, not override**: llm-here can
  upgrade a local `False` to `True` (CLI installed to a path
  `shutil.which` doesn't see, e.g. a per-user `~/.local/bin` that
  wasn't exported), but cannot downgrade a local `True` to `False` —
  `shutil.which` returning a path is ground truth for "this process
  can spawn the binary." Closes
  [#28](https://github.com/alpibrusl/agentspec/issues/28).

  Motivation: three sibling projects (caloron-noether, noether-grid,
  agentspec) were each reimplementing "which LLM CLI is installed" and
  had already drifted. `llm-here` is the shared detector; see
  [`alpibrusl/llm-here`](https://github.com/alpibrusl/llm-here) and the
  research note in
  [`noether/docs/research/llm-here.md`](https://github.com/alpibrusl/noether/blob/main/docs/research/llm-here.md).

- **Noether adapter now delegates `filesystem: scoped`.** noether v0.7.2
  ([PR noether#47](https://github.com/alpibrusl/noether/pull/47),
  closing [noether#39](https://github.com/alpibrusl/noether/issues/39))
  added `Vec<RwBind>` to `IsolationPolicy`, so agentspec's `scoped`
  trust mode now crosses over as `rw_binds` entries instead of raising
  `UnsupportedByNoetherAdapter` and falling back to direct-bwrap. The
  workdir keeps its `work_host` mapping; additional scope paths become
  named-struct `rw_binds` in the wire format. `filesystem: full`
  (host-passthrough) stays on the fallback path — noether-sandbox has
  no schema for `--bind / /`.

### Added

- **Noether isolation adapter** (Phase 2 of Proposal 002). Opt-in via
  `AGENTSPEC_ISOLATION_BACKEND=noether`; delegates sandboxing to the
  `noether-sandbox` binary (shipped in
  [noether v0.7.1](https://github.com/alpibrusl/noether/releases/tag/v0.7.1)
  / PR #37) instead of building the bwrap argv directly. Same sandbox
  primitive, one upstream implementation across both noether stage
  execution and agentspec trust enforcement. Writes the policy JSON to
  a tmpfile and invokes `noether-sandbox --policy-file <path>
  --isolate=bwrap --require-isolation --`, which gives us the
  TLS-dual-path plumbing, trusted-PATH bwrap resolution,
  UID-to-nobody mapping, and `128 + signum` exit-code convention from
  the upstream review loop for free. Default remains the direct-bwrap
  path until live parity data accumulates.
- **Scope of the adapter**: `TrustSpec.filesystem` values `none` and
  `read-only` delegate cleanly. `scoped` needs multi-path rw binds,
  which `noether-isolation` v0.7.1 doesn't expose; the adapter
  raises `UnsupportedByNoetherAdapter` and the runner falls back to
  the direct-bwrap path with a debug log. Tracked upstream in
  [noether#39](https://github.com/alpibrusl/noether/issues/39). A
  follow-up agentspec patch will flip `scoped` over once `rw_binds`
  ships.

### Fixed

- **`filesystem: none` / `read-only` under direct bwrap failed with
  `execvp <binary>: No such file or directory`.** Surfaced during the
  v0.5.1 noether-adapter smoke run — affected v0.5.0's direct-bwrap
  path equally. Root cause: `_existing_system_ro_binds` deduped
  symlink paths whose resolved target already fell under `/usr`, which
  on modern Debian/Ubuntu drops `/lib64` from the sandbox. ELF
  binaries hardcode `/lib64/ld-linux-x86-64.so.2` as their
  interpreter; the missing symlink made the kernel report a confusing
  "binary not found" on the outer binary rather than on its
  interpreter. Fix: bind each existing `_SYSTEM_RO_BINDS` entry at its
  original name. The twin-bind of `/usr/bin` via both `/usr` and
  `/bin` is benign — bwrap handles the overlap cleanly. Regression
  test in `tests/test_isolation.py`.

## [0.5.0] — 2026-04-19

The "Docker of agents" release — six load-bearing features that
together let you publish, distribute, pin, run, and audit an agent
with end-to-end cryptographic provenance. Validated in-process by
the `demo/pitch-smoke.sh` pipeline that exercises
push (multi-tenant) → pull (anonymous public-read) → lock (signed
Ed25519 envelope) → run (bwrap-isolated, signature-verified) →
record (tamper-evident log) end-to-end.

### Added

- **Lockfiles** (`agentspec.lock/v1`). Pin the resolver's output —
  runtime, model, tools, auth source, sha256 of the system prompt,
  host info — to a portable JSON artifact so CI / fleet deploys get a
  deterministic *setup*. (Model *behaviour* still can't be pinned;
  LLMs aren't deterministic — see
  `docs/proposals/001-execution-records.md` for why lockfiles promise
  attestation, not reproducibility.) System-prompt is stored as a
  hash only, never in full — locks are safe to commit to shared
  repos. Uses the same Ed25519 envelope shape as signed records and
  profile memories.

- **`agentspec lock <manifest>`** — create a lockfile from a manifest
  by resolving once and capturing the plan. Default output path is
  `<manifest>.lock`; override with `--out`. Signed output via
  `--sign-key-env VAR` (reads the Ed25519 private key from the named
  env var so it doesn't land in shell history or `ps aux`).

- **`agentspec verify-lock <lockfile> --pubkey <hex>`** — Ed25519
  verification with non-zero exit on failure. Suitable for CI
  gating. Distinguishes "malformed `--pubkey` argument" (operator
  error, distinct exit path) from `INVALID` (signature mismatch /
  tampering).

- **`agentspec run <manifest> --lock <lockfile>`** — skip resolve and
  run against the pinned plan. Fails fast when the manifest's current
  hash no longer matches the lock's recorded hash, so drift surfaces
  before the subprocess spawns. Adds `--require-signed --pubkey
  <hex>`: refuses to run unless the lock is a signed envelope that
  verifies against the named key — closes the tamper gap where a
  signed lock with mutated `resolved` fields but unchanged
  `manifest.hash` would otherwise run. Pair with CI to fail closed.

- **`agentspec.lock` Python module** — `LockFile`, `LockManager`,
  `plan_from_lock`. 36 new tests across `tests/test_lock.py` and
  `tests/test_cli_lock.py` covering schema, round-trip unsigned +
  signed, verify against correct/wrong/tampered/missing/unsigned,
  plan rehydration, `--require-signed` signature verification on
  `run --lock`, `--sign-key-env` signed envelope production, and
  distinct-error paths for malformed / wrong-length keys.

- **Runtime trust enforcement via bubblewrap.** Closes the gap the
  manifest's `trust: {filesystem, network, exec}` block had been
  declarative-only: the runner now wraps the spawned CLI in
  `bwrap` with a policy derived from `TrustSpec`. Fresh namespaces,
  cap-drop, `--die-with-parent`, workdir-only RW default, network
  gated by `trust.network`. See `docs/proposals/002-trust-enforcement-via-noether.md`
  for the design and why this ships as direct-bwrap instead of
  delegating to noether today (spoiler:
  [noether#36](https://github.com/alpibrusl/noether/issues/36)).

- **`agentspec run --via auto|bwrap|none`** plus
  `--unsafe-no-isolation` and `AGENTSPEC_ISOLATION` env fallback.
  `auto` (default) uses bwrap when installed, falls back on
  permissive manifests with a warning, **fails on tight manifests**
  when bwrap is missing (no silent downgrade).

- **`agentspec.runner.isolation` module.** `IsolationPolicy`
  dataclass, `policy_from_trust`, `select_backend`, `build_bwrap_argv`,
  `find_bwrap`, `is_tight_trust`. Decoupled from the renderer so a
  native-namespaces backend can consume the same policy later.

- **51 new tests** across `tests/test_isolation.py` (mapping +
  selection + argv rendering), `tests/test_runner_isolation.py`
  (runner integration with mocked bwrap and subprocess), and
  `tests/test_cli_isolation.py` (CLI flag parsing + env fallback).
  Includes regressions for the PR #17 live-smoke findings: system
  paths (`/usr`, `/bin`, `/etc`, …) are RO-bound in every
  bounded-fs mode so the runtime can exec, and mount ordering flips
  RW binds before RO binds so an RO scope sitting under a RW workdir
  lands last and wins.

- **Execution records.** Every `agentspec run` now writes a tamper-evident
  log to `{workdir}/.agentspec/records/<run-id>.json` capturing manifest
  hash, runtime, timing, exit code, and outcome. Never captures prompt
  content, outputs, or secrets. Opt-out with `emit_record=False` on
  `runner.execute()`. See `docs/proposals/001-execution-records.md` for
  design and the open questions still gating v0.5's scope. Records are
  identified by ULID (26-char Crockford base32, sortable, no PII).

- **Optional Ed25519 signing for records.** `RecordManager.write(record,
  private_key=hex)` wraps the record in the same envelope shape as signed
  profile memories (`payload` + `algorithm` + `signature` + `public_key`).
  Verification via `RecordManager.verify(run_id, pubkey)`. Unsigned records
  are plain JSON — still evidence, just not attested.

- **`agentspec records` CLI subcommand.** Three actions:
  `records list` (newest-first, filter by `--agent` hash),
  `records show <run-id>` (detail view),
  `records verify <run-id> --pubkey <hex>` (exits non-zero on invalid —
  suitable for CI gating). All support `--output json` for machine
  consumers.

- **34 new tests** across `tests/test_records.py` (unit: ULID,
  schema, round-trip, signing, tamper detection, listing),
  `tests/test_runner_records.py` (runner emission integration),
  and `tests/test_cli_records.py` (CLI invocation coverage).

- **Multi-tenant registry auth.** Set
  `AGENTSPEC_API_KEYS="alice:k1,bob:k2"` to give each publisher an
  isolated view of the registry. The portion before the first colon is
  the tenant ID; the remainder is the API key. Each tenant has its own
  `{base}/tenants/{tenant}/agents/` directory; cross-tenant reads,
  deletes, and lists surface as `404`. Mirrors the model used in
  noether-cloud's registry so agentspec can federate with it. Tenant
  IDs are restricted to `[A-Za-z0-9_-]+` to prevent path traversal.

- **Anonymous public reads preserved.** `GET /v1/agents` and
  `GET /v1/agents/{ref}` without an `X-API-Key` still return the
  aggregated catalog across all tenants. An authenticated read is
  scoped to the caller's tenant. This keeps "Docker Hub"-style public
  pulls working while letting authenticated clients enforce isolation.

- **20 new tests** in `tests/test_registry_multitenant.py` covering
  `_parse_keys` parsing, tenant-ID validation, push/delete/get/list
  isolation, legacy-key fallback, and storage-layer scoping.

- **`test-echo` pseudo-runtime.** Zero-dependency runtime mapping to
  POSIX `echo`. Lets integration tests, demo scripts, and CI smokes
  exercise the full push → pull → lock → run → record pipeline
  without installing any real LLM CLI (claude-code / gemini-cli /
  etc.). Registered in `RUNTIME_BINARIES`, `PROVIDER_MAP` (no auth),
  and the runner's builder dispatch.

- **`python -m agentspec`** entry point. The installed `agentspec`
  console-script shebang is fragile across venv relocations; `python
  -m agentspec` is portable and standard. Added via
  `src/agentspec/__main__.py`.

- **`demo/pitch-smoke.sh`** — 8-step end-to-end integration smoke
  that validates the whole pipeline using the `test-echo` runtime.
  Generates an Ed25519 keypair, stands up a local multi-tenant
  registry, pushes as alice, proves cross-tenant isolation on reads
  (bob's authenticated pull of alice's hash 404s), proves public-read
  aggregation (anonymous pull succeeds), locks with signing, runs
  under bwrap with `--require-signed --pubkey`, verifies the record,
  then tamper-tests the lock (must refuse). Prereqs: `bwrap`,
  `python3`, `curl`.

### Changed

- **Legacy `AGENTSPEC_API_KEY` now maps to tenant `default`.** Existing
  single-key deployments keep working unchanged. When both
  `AGENTSPEC_API_KEYS` and `AGENTSPEC_API_KEY` are set, the
  multi-tenant mapping wins — the legacy key stops being accepted.

- **Storage layout** moved from `{base}/agents/` to
  `{base}/tenants/{tenant}/agents/`. Existing installs should move
  `{base}/agents/*.json` → `{base}/tenants/default/agents/*.json` and
  likewise for `index.json`. The registry is alpha; auto-migration is
  not provided.

- **`push_agent` / `delete_agent` responses** now include the caller's
  `tenant` field. Additive — existing consumers that ignore unknown
  fields are unaffected.

- **`RegistryStorage()`** now reads `AGENTSPEC_REGISTRY_DIR` at
  construction time (was: at module import). Tests that monkeypatch
  the env per-function now get proper isolation.

### Fixed

- **Registry client didn't parse the native server's pull response.**
  `registry.client.pull_agent` expected either a Noether
  `{"ok", "data": {"result": {...}}}` envelope or a flat manifest at
  the top level; the agentspec-native server returns
  `{"hash": "...", "manifest": {...}}` — neither shape was
  recognised. Anonymous pulls against agentspec's own registry
  silently fell through to a `/stages/{id}` Noether fallback that
  doesn't exist on the native server, returning `None` → CLI
  `NOT_FOUND`. Surfaced by the end-to-end smoke (PR #20).

- **Runner didn't flush stdout before `subprocess.run`.** When
  `agentspec run` was piped (e.g. `agentspec run | tee`), Python's
  block-buffered stdout held the "Launching…" log line while the
  subprocess's line-buffered output went out immediately, producing
  an inverted log order at process exit. Cosmetic but surprising.
  Fix: `sys.stdout.flush()` + `sys.stderr.flush()` before the
  subprocess spawn.

## [0.4.0] — 2026-04-17

The provisioner: agentspec now materialises the agent's identity, rules,
skill instructions, and MCP server registrations into the config files
each CLI natively reads — before spawning the process. Previously,
agentspec declared *what* an agent needed but left the caller (e.g.
caloron-noether) to wire it up per-runtime. Now agentspec owns the
full path from manifest to running CLI.

### Added

- **`DependencySpec` model** — declares what a tool or skill needs
  installed: `pip`, `npm`, `cargo`, `nix` packages, `setup` commands,
  and required `env` vars. Used by `McpServerSpec.requires` and
  `SkillSpec.requires`.

- **`McpServerSpec` model** in `agentspec.parser.manifest`. Structured
  MCP server definition with `name`, `url`, `transport` (stdio/http/sse),
  `command`, `args`, `env`, `headers`, `requires`. Accepted alongside
  plain strings and legacy dicts in `tools.mcp`.

- **`SkillSpec` model** — enriched skill with optional `requires`.
  Skills can remain plain strings or become dicts with dependency
  declarations. Plain strings are the common case; enriched skills
  are for orchestrators that need to install deps before running.

- **`agentspec.runner.provisioner` module** — the core addition.
  `provision(plan, manifest, workdir)` writes runtime-specific config
  files before the CLI spawns:

  **Instruction files** (soul + rules + traits + skill instructions):
  | Runtime    | File                        |
  |------------|-----------------------------|
  | claude-code | `CLAUDE.md`                |
  | gemini-cli  | `GEMINI.md`                |
  | cursor-cli  | `.cursorrules`             |
  | codex-cli   | `AGENTS.md`                |
  | opencode    | `.open-code/instructions.md`|
  | aider       | `.aider.conf.yml`          |
  | goose       | *(uses --system flag)*     |

  **MCP config files** (server registrations):
  | Runtime    | File                        |
  |------------|-----------------------------|
  | claude-code | `.mcp.json`                |
  | cursor-cli  | `.cursor/mcp.json`         |
  | gemini-cli  | `.gemini/settings.json`    |
  | codex-cli   | `codex.json`               |
  | opencode    | `.open-code/mcp.json`      |

- **Well-known MCP server registry** — 13 servers (github, postgres,
  slack, filesystem, brave-search, google-scholar, arxiv, jira,
  playwright, puppeteer, noether, and aliases). Plain string entries
  like `- github` in `tools.mcp` are auto-expanded to their full
  server spec at provision time.

- **`SKILL_INSTRUCTIONS` dictionary** — 19 skill-specific instruction
  strings (web-search, code-execution, git, github, python-development,
  rust-development, typescript-development, pytest-testing, etc.).
  Injected as `## Skill Instructions` sections in each instruction file.

- **`provision_install()` function** — optional second step that
  registers MCP servers via CLI commands (`claude mcp add`,
  `gemini mcp add`, `codex mcp add`, `cursor --add-mcp`) and
  installs declared dependencies (pip, npm, cargo, setup commands).
  Returns a list of human-readable notes about what was done.

- **`WELL_KNOWN_SKILL_DEPS` registry** — 9 skills with default
  dependency declarations (data-analysis → pandas/numpy,
  pytest-testing → pytest/pytest-cov, browser → playwright, etc.).

- **Folder scaffolding** — `provision()` creates the directory
  structure each CLI expects before writing config files:
  `.claude/`, `.cursor/`, `.gemini/`, `.open-code/`.

- **`provision()` and `provision_install()` exported** from the
  `agentspec` namespace.

### Changed

- **Runner calls provisioner before `build_command()`.** `execute()`
  now accepts an optional `workdir` parameter and runs
  `provision(plan, manifest, workdir)` before spawning the CLI.

- **System prompt delivery simplified.** Command builders for codex-cli,
  cursor-cli, opencode, and gemini-cli no longer prepend `plan.system_prompt`
  to the user prompt or write framework-specific files directly. The
  provisioner handles it via native instruction files. Claude-code
  (`--system-prompt`) and goose (`--system`) still pass it as a flag.

- **GEMINI.md write moved from `_build_gemini_cmd` to provisioner.**

### Tests

- 170 → 247 green (77 new provisioner tests covering instruction files,
  MCP configs, well-known server expansion, normalisation, no-overwrite
  guards, end-to-end provisioning, parametric runtime coverage, folder
  scaffolding, DependencySpec, enriched skills, and provision_install).

### Migration from 0.3.x

- **No breaking changes to the manifest format.** Existing `tools.mcp`
  entries (strings and dicts) continue to work unchanged.
- **Skills can now be dicts.** `skills: [{name: "x", requires: {pip: [y]}}]`
  is accepted alongside plain strings. The resolver extracts the name
  for skill resolution; the provisioner uses `requires` for installation.
- **Behavioral change:** CLIs that previously received system prompts
  prepended to the user prompt now receive them via native instruction
  files. The user prompt is cleaner; the system instructions are in the
  file the CLI is designed to read.
- **New dependency for aider config:** `pyyaml` (already a transitive
  dep via pydantic, but now used directly for `.aider.conf.yml` writing).

## [0.3.3] — 2026-04-16

Continued the post-install audit: installed cursor-agent 2026.04.15,
opencode 1.4.6, and aider 0.86.2 rootless, ran live dry-runs against
each. **Every CLI had at least one gap vs its real `--help`** — fixed
here.

### Added

- **`cursor` provider prefix in `PROVIDER_MAP`.** Without this entry,
  manifests declaring `cursor/<model>` fell through as "unknown
  provider" and cursor-cli was unreachable via the resolver despite
  the runtime being registered. Caught by live dry-run.
- **cursor `--model <name>` threading.** `cursor-agent --model` takes
  cursor-specific names (`gpt-5`, `sonnet-4`, `sonnet-4-thinking`).
- **cursor `--force` under AGENTSPEC_GYM=1** for tool-approval bypass.
- **opencode `-m/--model <provider/model>` threading.** opencode's
  real flag takes a `provider/model` pair; manifest's caller-facing
  `opencode/` prefix is stripped once so we pass what opencode expects.
- **aider `--yes-always` under AGENTSPEC_GYM=1** for unattended runs.

### Fixed

- **cursor `-p` is now a bare flag**, not a prefix for the prompt.
  Previous `[-p, <prompt>]` worked by accident (cursor-agent parsed
  `-p` as a boolean and the next arg as positional) but the idiomatic
  shape separates them.

### Verified live (v0.3.3 argv against installed binaries)

```
cursor-agent -p --output-format text --force --model sonnet-4 "<prompt>"
opencode run -m anthropic/claude-sonnet-4-6 "<prompt>"
aider --yes-always --model claude-sonnet-4-6 --message "<prompt>"
```

All three match the binary's accepted argv exactly.

### Tests

- 161 → 170 green (9 new + 6 updated to v0.3.3 shapes).

### Still unvalidated

`ollama` is in the catalogue but couldn't be installed rootless —
GitHub release assets 404 via the sandbox's network. No code changes
this release; pinned to pre-existing builder.

## [0.3.2] — 2026-04-16

Post-install verification of v0.3.1: both goose (1.30.0) and codex-cli
(0.121.0) installed rootless on a test box, and the argv agentspec
produces was confirmed against `codex exec --help` and `goose run
--help` from the live binaries. One small fix surfaced:

### Fixed

- **codex-cli subscription auth fallback.** The resolver previously
  rejected codex-cli with "OPENAI_API_KEY not set" when no API key
  was in the env. But codex also supports subscription-style auth
  via `codex login` (browser OAuth or device code) — same pattern
  as `claude login` / gemini's logged-in CLI mode. Resolver now
  treats codex-cli the same as claude-code and gemini-cli for the
  subscription-fallback path: if the binary is on PATH but no API
  key is set, assume the CLI is logged in rather than skipping
  the candidate. Users with just `codex login` and no env var are
  no longer wrongly rejected.

### Verified

Live against installed binaries (v0.3.1 claims validated):

  codex exec --full-auto -m gpt-5 "<prompt>"   ← what agentspec produces
  goose run --model claude-sonnet-4-6 -t "<prompt>"  ← what agentspec produces

Both match `--help` output exactly.

## [0.3.1] — 2026-04-16

Extends v0.3.0's parity sweep to codex-cli (which had its own set of
broken flags) and adds support for Block's `goose`.

### Added

- **`goose` runtime**. MCP-native agent from Block; non-interactive
  form per https://goose-docs.ai/docs/guides/goose-cli-commands is
  `goose run -t "<prompt>"`. Supported flags:
  - `--model <name>` — bare model name with provider prefix stripped
  - `--system <text>` — **real** system-prompt flag (unlike
    codex/cursor/opencode where we have to prepend)
  - `-t <prompt>` — the user prompt
  Provider/auth managed by goose itself via `goose configure`; our
  resolver just needs the binary on PATH. Handles MCP-heavy agent
  manifests naturally because goose's entire design is MCP-first.

### Fixed

- **codex-cli uses `exec` subcommand now.** Previously built
  `codex <prompt>` which drops into the interactive TUI; modern codex
  requires `codex exec <prompt>` for non-interactive runs. Verified
  against https://developers.openai.com/codex/cli/reference.
- **codex-cli autonomous mode via `--full-auto`.** Added under
  `AGENTSPEC_GYM=1`, matching the treatment other autonomous CLIs get
  (claude's `--dangerously-skip-permissions`, gemini's `-y`).
- **codex-cli `-m/--model` threading.** Same gap as claude/gemini had —
  manifest's `model.preferred` was silently dropped.
- **codex-cli `--instructions` flag removal.** The previous builder
  wrote `plan.system_prompt` to a temp file and passed
  `--instructions <tmpfile>`, but codex doesn't have that flag.
  Modern codex rejected the argv with "unknown option". System prompts
  now prepend to the user prompt (same pattern as cursor/opencode).

### Not added (deliberate — flagged in commits)

- **Amazon Q Developer CLI**. The open-source `q` binary is "no longer
  actively maintained" per its own GitHub; AWS moved to Kiro which is
  closed-source. Speculative integration would generate exactly the
  silent-drift bugs the parity sweeps have been fixing. Will revisit
  if a user explicitly asks and can share the current flag contract.
- **Sourcegraph Cody, Continue, Windsurf**. Each exists as a CLI but
  field demand hasn't surfaced, and each has its own flag-drift
  surface to maintain. Adding only when asked.

### Tests

- 139 → 161 green. 22 new: 7 codex (exec subcommand, --full-auto gating,
  -m threading, --instructions removed, system-prompt prepended, model
  name stripping parametrized), 6 goose (dispatch reachability, run
  subcommand, --model, --system flag, empty-model guard, model name
  stripping parametrized), and the parity table was extended to pin
  goose → goose.

### Upgrading from 0.3.0

No breaking changes. New `goose` runtime is opt-in via
`model.preferred: [goose/...]` or the usual provider-prefix shapes
like `anthropic/claude-sonnet-4-6` when the claude-code runtime isn't
available. codex-cli behaviour changes for all callers — the old
argv was broken against modern codex anyway, so there's no
well-formed invocation that will regress.

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
