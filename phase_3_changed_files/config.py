"""Which model, on which arm. The only file in this phase that names a provider.

The talk is given on GitHub Copilot and the team runs on it, so it is the arm
when none is named; like everything that is not Gemini it goes through
LiteLLM, so the model is a `LiteLlm` wrapper. Gemini, which ADK speaks
natively, is a plain model string. Both are the same `LlmAgent` to the rest
of the code; `REVIEW_PROVIDER` in the central
`.env` is the one switch, and ADK loads that file before it imports this one.
"""

from __future__ import annotations

import os

from google.adk.models.lite_llm import LiteLlm

DEFAULTS = {"gemini": "gemini-2.5-flash", "copilot": "gpt-4.1"}


def build_model() -> str | LiteLlm:
    """The model for `REVIEW_PROVIDER`: a Gemini model name, or Copilot through LiteLLM."""
    provider = os.environ.get("REVIEW_PROVIDER", "").strip().lower() or "copilot"
    if provider not in DEFAULTS:
        raise ValueError(f"REVIEW_PROVIDER must be one of {sorted(DEFAULTS)}, not {provider!r}")
    model = os.environ.get("REVIEW_MODEL", "").strip() or DEFAULTS[provider]
    if provider == "gemini":
        return model
    # Copilot authenticates with a cached device-flow token, not a key: `uv run python scripts/copilot_login.py`, once.
    return LiteLlm(model=f"github_copilot/{model}")
