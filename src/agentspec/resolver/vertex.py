"""Vertex AI backend integration for agentspec.

When Vertex AI is configured (via standard GCP env vars + ADC), agentspec
routes the existing CLIs (claude-code, gemini-cli, aider, opencode)
through Vertex AI instead of direct provider APIs. This gives:

- Single-vendor billing and audit trail (CloudLogging)
- EU data residency by default (europe-west1)
- IAM-based auth instead of per-provider API keys
- Access to Anthropic Claude + Google Gemini + others via Model Garden

Detection priority:
1. AGENTSPEC_VERTEX_PROJECT (explicit, highest)
2. GOOGLE_CLOUD_PROJECT (standard GCP env)
3. None → direct provider APIs (existing behavior)

Region defaults to europe-west1 (Belgium) for EU data residency.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


# europe-west1 (Belgium): broadest model availability in EU + GDPR primary region
DEFAULT_LOCATION = "europe-west1"


@dataclass(frozen=True)
class VertexConfig:
    project: str
    location: str

    def __str__(self) -> str:
        return f"vertex-ai (project={self.project}, region={self.location})"


def detect_vertex_ai() -> Optional[VertexConfig]:
    """Detect Vertex AI configuration. Returns None if not configured."""
    project = (
        os.environ.get("AGENTSPEC_VERTEX_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("VERTEX_PROJECT")
    )
    if not project:
        return None

    location = (
        os.environ.get("AGENTSPEC_VERTEX_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or os.environ.get("VERTEX_LOCATION")
        or DEFAULT_LOCATION
    )

    # Verify Application Default Credentials are usable.
    # Try gcloud first (faster to check), fall back to google-auth import.
    if not _adc_available():
        return None

    return VertexConfig(project=project, location=location)


def _adc_available() -> bool:
    """Check if Application Default Credentials are accessible."""
    # Path 1: gcloud installed and ADC configured
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Path 2: google.auth library can find creds (works in Cloud Run, GCE, etc.)
    try:
        import google.auth  # type: ignore

        google.auth.default()
        return True
    except Exception:
        return False


# ── Per-runtime env var mapping ───────────────────────────────────────────────


def vertex_env_for_runtime(runtime: str, config: VertexConfig) -> dict[str, str]:
    """Return env vars to inject when spawning <runtime> against Vertex AI.

    Empty dict means "this runtime cannot use Vertex AI" (e.g. codex-cli).
    """
    base = {
        "GOOGLE_CLOUD_PROJECT": config.project,
        "GOOGLE_CLOUD_LOCATION": config.location,
    }

    if runtime == "claude-code":
        # Anthropic's official Vertex AI mode
        return {
            **base,
            "CLAUDE_CODE_USE_VERTEX": "1",
            "CLOUD_ML_REGION": config.location,
            "ANTHROPIC_VERTEX_PROJECT_ID": config.project,
        }

    if runtime == "gemini-cli":
        # Google's official Gemini CLI Vertex mode
        return {
            **base,
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
        }

    if runtime == "aider":
        # aider uses LiteLLM under the hood
        return {
            **base,
            "VERTEX_PROJECT": config.project,
            "VERTEX_LOCATION": config.location,
        }

    if runtime == "opencode":
        # opencode (per https://opencode.ai/docs/providers/ for
        # google-vertex-ai) reads:
        #   - GOOGLE_CLOUD_PROJECT (present in ``base``)
        #   - VERTEX_LOCATION (NOT GOOGLE_CLOUD_LOCATION which ``base``
        #     sets for everyone else — opencode specifically uses
        #     VERTEX_LOCATION, defaulting to "global" if unset)
        #   - GOOGLE_APPLICATION_CREDENTIALS — handled transparently
        #     because os.environ is inherited; if the user has set
        #     this variable, build_env passes it through unchanged
        return {
            **base,
            "VERTEX_LOCATION": config.location,
        }

    if runtime == "ollama":
        # Local model — no Vertex routing
        return {}

    if runtime == "codex-cli":
        # OpenAI is NOT in Vertex Model Garden; cannot route
        return {}

    if runtime == "cursor-cli":
        # Cursor uses its own backend; not relevant
        return {}

    if runtime == "goose":
        # goose's provider/model selection is config-driven via
        # `goose configure`. If the user has configured it to route
        # through Vertex AI directly, goose handles that itself —
        # passing GCP base env through is enough to give it the option.
        return base

    # Unknown runtime — pass through base GCP env so it has the option
    return base


# ── Vertex-aware provider routing ─────────────────────────────────────────────

# Providers that CAN route through Vertex AI when it's configured.
# (codex-cli/openai is excluded because OpenAI models are not on Vertex.)
VERTEX_PROVIDERS = frozenset(["claude", "anthropic", "gemini", "google"])


def can_route_through_vertex(provider: str) -> bool:
    """Whether a model provider prefix can be served by Vertex AI."""
    return provider in VERTEX_PROVIDERS
