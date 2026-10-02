"""Which model, on which arm, and what the agent answers when it cannot be reached. The only file naming a provider.

The talk is given on GitHub Copilot and the team runs on it, so it is the arm
when none is named; like everything that is not Gemini it goes through
LiteLLM, so the model is a `LiteLlm` wrapper. Gemini, which ADK speaks
natively, is a plain model string. Both are the same `LlmAgent` to the rest
of the code; `REVIEW_PROVIDER` in the central
`.env` is the one switch, and ADK loads that file before it imports this one.
"""

from __future__ import annotations

import os

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

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
    # LiteLLM is this arm's alone, imported here: at the top of a command it cost about a second of every start, and
    # on its own import it read `.env` unless told it runs in production, as ADK tells it, and fetched a price list
    # unless `LITELLM_LOCAL_MODEL_COST_MAP` is set.
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    import litellm

    litellm.suppress_debug_info = True  # else a red "Give Feedback" banner on stdout with every error
    return LiteLlm(model=f"github_copilot/{model}")


def request_config() -> types.GenerateContentConfig:
    """Temperature zero for every agent that judges: a severity is a decision, and a demo that
    gives a different verdict on every run teaches the wrong lesson. Mapped on both arms."""
    return types.GenerateContentConfig(temperature=0.0)


def describe(error: Exception) -> str:
    """The provider's error as one readable line: its code and its own sentence where it has them, else its text.

    genai raises a `ClientError` whose `str` is the whole JSON body and whose
    `.message` is the sentence a person wants — "You exceeded your current
    quota … Please retry in 19s"; LiteLLM's errors carry `.status_code` and a
    `.message` that begins with their own class name, dropped here so the
    class is named once. One line, cut at 400 characters, and the cut is named.
    """
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(getattr(error, "message", None) or error).removeprefix(f"litellm.{type(error).__name__}: ")
    line = " ".join((f"{code}: {message}" if code else message).split())
    return line if len(line) <= 400 else f"{line[:400]} [… cut at 400 characters]"


def when_the_model_fails(callback_context: CallbackContext, llm_request: LlmRequest, error: Exception) -> LlmResponse:
    """The agent's answer when the provider refuses the call: a sentence, never a traceback.

    ADK's `on_model_error_callback`: a response returned here takes the
    exception's place, so the turn ends with something a person can read.
    Measured before it, a quota error under `adk run` was sixty lines of
    traceback; it is one line now. The error code is the one ADK gives an
    error that escapes: the API's own status where there is one, else the
    class name. An agent that answers in a schema answers in it — no
    findings, the sentence as its summary — because ADK saves the answer
    under `output_key` through that schema. The sentence is left in state
    too, under `temp:failure`, so the agent after this one can tell there is
    nothing to judge; `temp:` is ADK's invocation lifetime, so a later turn
    starts clean — measured without it, one failed turn made every reviewer
    skip for the rest of the session.
    """
    status = getattr(error, "status", None)
    kind = status if isinstance(status, str) else type(error).__name__
    why = describe(error)
    callback_context.state["temp:failure"] = f"{callback_context.agent_name}: {kind}: {why}"
    text = f"I could not reach the model: {kind}: {why}"
    if (schema := llm_request.config.response_schema) is not None:
        text = schema(summary=text).model_dump_json()
    return LlmResponse(content=types.ModelContent(text), error_code=kind, error_message=why)
