# Vertex AI Backend

Route any compatible CLI runtime through Google Cloud Vertex AI instead of direct provider APIs.

## Why

- **Single-vendor billing & audit trail** (CloudLogging captures every call)
- **EU data residency by default** (`europe-west1`)
- **IAM auth** instead of per-provider API keys (no `ANTHROPIC_API_KEY` to rotate)
- **Model Garden access**: Anthropic Claude + Google Gemini + Llama + Mistral + others, all under one auth
- **Compliance**: SOC2, ISO27001, HIPAA, EU GDPR — what your security team probably already approved

## Setup

```bash
# 1. Authenticate (any one of these)
gcloud auth application-default login        # interactive
# or, in CI / Cloud Run:
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# 2. Tell agentspec which project to use
export GOOGLE_CLOUD_PROJECT=my-project

# 3. (Optional) override the region — defaults to europe-west1
export GOOGLE_CLOUD_LOCATION=europe-west4
```

That's it. AgentSpec auto-detects the configuration. Verify with:

```bash
agentspec resolve my-agent.agent
# decisions:
#   Vertex AI detected: vertex-ai (project=my-project, region=europe-west1)
#   selected claude/claude-sonnet-4-6 via claude-code (Vertex AI: europe-west1)
```

## Per-runtime mapping

When AgentSpec routes through Vertex AI, it injects the right env vars
for each CLI:

| CLI | Mechanism | Env vars set |
|---|---|---|
| **claude-code** | Anthropic's official Vertex mode | `CLAUDE_CODE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION` |
| **gemini-cli** | Google's official Vertex mode | `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| **aider** | Via LiteLLM Vertex provider | `VERTEX_PROJECT`, `VERTEX_LOCATION` |
| **opencode** | Standard GCP env vars | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| **codex-cli** | ❌ OpenAI not on Vertex Model Garden | (uses OpenAI direct API) |
| **ollama** | ❌ Local model | (no Vertex routing) |

## Routing precedence

When both Vertex AI and direct provider API keys are configured, Vertex
AI wins for **routable providers** (`claude`, `anthropic`, `gemini`,
`google`).

For non-routable providers (`openai`, `local`), agentspec uses the
direct API even when Vertex is configured.

## Region selection

Default: `europe-west1` (Belgium) — broadest model coverage in EU and
GDPR-primary region.

Other useful EU regions:

| Region | Notes |
|---|---|
| `europe-west1` | Belgium. Default. Best Gemini + Claude availability. |
| `europe-west4` | Netherlands. Alternative if you need it for residency. |
| `europe-southwest1` | Madrid. Latency-friendly for SP/PT workloads. |

Set explicitly when needed:

```bash
export GOOGLE_CLOUD_LOCATION=europe-west4
# or
export AGENTSPEC_VERTEX_LOCATION=europe-west4
```

## Env var precedence (project)

Highest to lowest:

1. `AGENTSPEC_VERTEX_PROJECT` (explicit, agentspec-specific)
2. `GOOGLE_CLOUD_PROJECT` (standard GCP env)
3. `VERTEX_PROJECT` (some tooling uses this)

Same for location: `AGENTSPEC_VERTEX_LOCATION` > `GOOGLE_CLOUD_LOCATION` > `VERTEX_LOCATION` > `europe-west1` (default).

## What about Model Garden Anthropic models?

Vertex Model Garden serves Anthropic Claude models on EU-resident
infrastructure. AgentSpec recognizes provider prefixes `claude/` and
`anthropic/` and routes them to claude-code with Vertex env vars. The
actual model you request must be available in your region.

Check availability: <https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models>

## Disabling

Just unset the env vars:

```bash
unset GOOGLE_CLOUD_PROJECT
```

Or set a non-routable model in your `.agent`:

```yaml
model:
  preferred:
    - openai/o3              # uses codex-cli direct, never Vertex
    - local/llama3:70b       # uses ollama, never Vertex
```

## Verifying it actually went through Vertex

After running an agent, check CloudLogging:

```bash
gcloud logging read 'resource.type="aiplatform.googleapis.com/Endpoint"' \
  --project=$GOOGLE_CLOUD_PROJECT --limit=5
```

You should see your model invocations there. If you don't, agentspec
fell back to direct API for some reason — check the resolver decisions
with `agentspec resolve --output json` and look at `auth_source`.
