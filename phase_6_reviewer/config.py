"""Which model, on which arm, and what a request to it looks like. The only file in this phase that names a provider.

The talk is given on GitHub Copilot and the team runs on it, so it is the arm
when none is named; like everything that is not Gemini it goes through
LiteLLM, so the model is a `LiteLlm` wrapper. Gemini, which ADK speaks
natively, is a plain model string. Both are the same `LlmAgent` to the rest
of the code; `REVIEW_PROVIDER` in the central
`.env` is the one switch, and ADK loads that file before it imports this one.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from google.adk.models.lite_llm import LiteLlm
from google.adk.planners import BasePlanner, BuiltInPlanner
from google.genai import types

DEFAULTS = {"gemini": "gemini-2.5-flash", "copilot": "gpt-4.1"}


#: A bearer token in a log line. LiteLLM's debug dump masks a request's headers but prints its body whole, and the
#: Copilot arm carries its token in the body's `extra_headers`.
_BEARER = re.compile(r"(Bearer\s+)[^\s'\",}]+")


class _HideBearer(logging.Filter):
    """Every LiteLLM log line with its bearer token hidden. Measured with a fake token: `adk web -v`, which writes its
    log where any account on the machine can read it, printed the Copilot token whole."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = _BEARER.sub(r"\1[REDACTED]", record.getMessage()), ()
        return True


_HIDE_BEARER = _HideBearer()


def provider() -> str:
    """The arm `REVIEW_PROVIDER` names, validated once for every function below.

    Validated here and nowhere else: three functions read the variable, and
    when each read it for itself a typo in the central `.env` surfaced as a
    `ValueError` from whichever ran first — at import, before argparse.
    """
    arm = os.environ.get("REVIEW_PROVIDER", "").strip().lower() or "copilot"
    if arm not in DEFAULTS:
        raise ValueError(f"REVIEW_PROVIDER must be one of {sorted(DEFAULTS)}, not {arm!r}")
    return arm


def model_name() -> str:
    """The model `REVIEW_MODEL` names, else the arm's default."""
    return os.environ.get("REVIEW_MODEL", "").strip() or DEFAULTS[provider()]


def serving() -> str:
    """What a run's model calls go to, for the report: the model, its arm, and Vertex AI when the environment sends
    the Gemini arm there. Every entry point lets the shell's variables win over `.env` — ADK restores what was set
    before it loads the file — so a stale export picked the arm or the model unseen."""
    arm = provider()
    vertex = arm == "gemini" and os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in {"1", "true"}
    return f"{model_name()} on {arm}" + (" through Vertex AI" if vertex else "")


def build_model() -> str | LiteLlm:
    """The model for `REVIEW_PROVIDER`: a Gemini model name, or Copilot through LiteLLM."""
    arm, model = provider(), model_name()
    if arm == "gemini":
        return model
    # Copilot authenticates with a cached device-flow token, not a key: `uv run python scripts/copilot_login.py`, once.
    logging.getLogger("LiteLLM").addFilter(_HIDE_BEARER)  # once: a filter already there is not added again
    # LiteLLM is this arm's alone, imported here: at the top of a command it cost about a second of every start, and
    # on its own import it read `.env` unless told it runs in production, as ADK tells it, and fetched a price list
    # unless `LITELLM_LOCAL_MODEL_COST_MAP` is set.
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    import litellm

    litellm.suppress_debug_info = True  # else a red "Give Feedback" banner on stdout with every error
    return LiteLlm(model=f"github_copilot/{model}")


def lane_planner(thinking_budget: int) -> BasePlanner | None:
    """A thinking budget where the provider has one; nothing where it does not.

    `BuiltInPlanner` is configuration only: it sets the budget on the request
    and adds no prompt text, and only Gemini honours it. ADK's alternative for
    other models is `PlanReActPlanner` — prompt engineering that runs anywhere —
    but it collides with `output_schema`, so this demo keeps the schema and
    states plainly that the reasoning lever is absent on Copilot.
    """
    if provider() == "gemini":
        return BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget))
    return None


#: Seconds one model call may take; a hung provider call would otherwise hang the run for ever.
REQUEST_TIMEOUT_S = 180.0


def request_config() -> types.GenerateContentConfig:
    """What every judging call carries, on both arms: temperature zero, and a deadline.

    A severity is a decision, and a demo that gives a different verdict on
    every run teaches the wrong lesson. The deadline is one number for both
    arms: genai reads `HttpOptions.timeout` in milliseconds, and ADK's LiteLLM
    wrapper converts it to LiteLLM's seconds (`lite_llm.py`, 2.9.2); on the
    Copilot arm the OpenAI SDK under LiteLLM retries twice of its own accord. A
    call past it is a model error like any other, which `ReportProviderErrors`
    turns into that lane's own answer.
    """
    return types.GenerateContentConfig(
        temperature=0.0, http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT_S * 1000))
    )


def copilot_token() -> Path:
    """Where LiteLLM caches the Copilot device-flow token.

    The same two variables and defaults `scripts/copilot_login.py` reads; a
    copy rather than an import because a phase folder must run on its own.
    """
    token_dir = os.environ.get("GITHUB_COPILOT_TOKEN_DIR", "~/.config/litellm/github_copilot")
    return Path(token_dir).expanduser() / os.environ.get("GITHUB_COPILOT_ACCESS_TOKEN_FILE", "access-token")


def require_ready() -> str | None:
    """Why the chosen arm cannot run, or None. Called by the CLI before anything is spent, never at import."""
    try:
        arm = provider()
    except ValueError as exc:
        return str(exc)
    if arm == "gemini" and not os.environ.get("GOOGLE_API_KEY", "").strip():
        return "REVIEW_PROVIDER=gemini needs GOOGLE_API_KEY in the central .env"
    # An empty file is no token: LiteLLM would start its own device login inside the first model call.
    if arm == "copilot" and not ((token := copilot_token()).is_file() and token.stat().st_size):
        return (
            f"REVIEW_PROVIDER=copilot needs a cached token at {token}; "
            f"run `uv run python scripts/copilot_login.py` once"
        )
    return None
