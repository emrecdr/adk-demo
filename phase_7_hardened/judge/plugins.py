"""Three plugins on the App, which no agent can opt out of.

A callback is per agent and is where "this tool needs an allowlist" belongs. A
plugin is registered once on the `App` and applies to every agent, which is
where "we never send a credential to a provider", "we always know what a run
cost", "a run has a budget" and "a provider error is one lane's answer, not the
graph's death" belong. `@override` marks each hook as one ADK calls by keyword:
a misnamed parameter would build fine and fail on the first live call. The
secret shapes themselves live in `core/secrets.py`, shared with the gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, override

from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from ..core.secrets import scrub, scrub_value
from ..core.text import REASON_MAX_CHARS, cut_at, squash

#: Room reserved for an answer on top of a request's own size, in tokens; a lane's typed review is well under it.
ANSWER_ALLOWANCE = 1_000


def _text_parts(llm_request: Any) -> Iterator[Any]:
    """Every part of the request's conversation that carries text; the instruction sits on its config, not here."""
    return (part for content in llm_request.contents or [] for part in content.parts or [] if part.text)


def describe(error: Exception) -> str:
    """The provider's error as one readable line: its code and its own sentence where it has them, else its text.

    genai raises a `ClientError` whose `str` is the whole JSON body and whose
    `.message` is the sentence a person wants — "You exceeded your current
    quota … Please retry in 19s"; LiteLLM's errors carry `.status_code` and a
    `.message` that begins with their own class name, dropped here so the
    class is named once. One line, cut at `REASON_MAX_CHARS`, the cut named.
    """
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(getattr(error, "message", None) or error).removeprefix(f"litellm.{type(error).__name__}: ")
    return cut_at(squash(f"{code}: {message}" if code else message), REASON_MAX_CHARS)


class RedactSecretsPlugin(BasePlugin):
    """Scrubs known secret shapes from every tool result and every outgoing request. Fail-closed."""

    def __init__(self, name: str = "redact_secrets") -> None:
        super().__init__(name=name)
        self.redacted = 0

    @override
    async def before_model_callback(self, *, callback_context: Any, llm_request: Any) -> LlmResponse | None:
        """Returning a response SKIPS the model call: if scrubbing fails, nothing unscrubbed is sent."""
        try:
            for part in _text_parts(llm_request):
                part.text, count = scrub(part.text)
                self.redacted += count
            instruction = llm_request.config.system_instruction
            if isinstance(instruction, str):
                llm_request.config.system_instruction, count = scrub(instruction)
                self.redacted += count
            elif instruction is not None:  # ADK 2.9.2 writes a string: any other shape is refused, never sent unread
                raise TypeError(f"the system instruction is a {type(instruction).__name__}; only a string is scrubbed")
        except Exception as exc:  # noqa: BLE001 -- a broken scrubber must not send unscrubbed text
            return LlmResponse(error_code="REDACTION_FAILED", error_message=f"refusing to call the model: {exc}")
        return None

    @override
    async def after_tool_callback(
        self, *, tool: Any, tool_args: Any, tool_context: Any, result: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Returning a dict REPLACES the tool's result before the model sees it."""
        scrubbed, count = scrub_value(result)
        self.redacted += count
        return scrubbed if count else None


class ReportProviderErrors(BasePlugin):
    """A provider error is the lane's own answer, not the graph's death.

    Measured on ADK 2.9.2 without this: an exception a lane let escape tore
    the whole `Workflow` down and the runner re-raised it, so a sibling still
    in flight was lost with it. ADK's model-error hook runs when a call
    raises; returning a response yields it in the exception's place — the
    path the redaction plugin's refusal already takes — so the lane ends with
    an error event under its own name, its `output_key` stays unwritten, and
    every other lane finishes by construction. The graphs before answer a failure
    through each agent's own `on_model_error_callback`; this is the same hook,
    once, on the App, so no agent can opt out. A call past the request
    deadline (`config.REQUEST_TIMEOUT_S`) arrives here the same way, after
    the client's own retries are spent.
    """

    def __init__(self, name: str = "provider_errors") -> None:
        super().__init__(name=name)

    @override
    async def on_model_error_callback(
        self, *, callback_context: Any, llm_request: Any, error: Exception
    ) -> LlmResponse | None:
        """Two answers. An agent that answers in a schema — a lane — answers nothing: its key stays unwritten, a hole
        the code that decides names and never approves over, where a review with no findings would read as an
        approval. An agent that answers in prose — the intake or the verdict, in chat — answers the sentence, as
        an agent's own hook did before, and leaves it under `temp:failure` for the lanes' guard: ADK's
        invocation lifetime, so a later turn starts clean. The schema is read off the request; an agent given tools
        beside an `output_schema` gets a tool instead of a response schema on some models, and would count as prose."""
        why = describe(error)
        status = getattr(error, "status", None)
        kind = status if isinstance(status, str) else type(error).__name__  # ADK's own rule for an error that escapes
        if llm_request.config.response_schema is not None:
            return LlmResponse(error_code=kind, error_message=why)
        reason = f"{kind}: {why}"
        callback_context.state["temp:failure"] = f"{callback_context.agent_name}: {reason}"
        return LlmResponse(
            content=types.ModelContent(f"I could not reach the model: {reason}"), error_code=kind, error_message=why
        )


class UsageLedger(BasePlugin):
    """Counts model calls and tokens per agent — and, given a ceiling, refuses the call that would pass it.

    Three lanes call at once, so a ceiling checked against tokens already
    spent would let all three through and be passed by all three. Every call
    therefore reserves its own cost first — its request in characters over
    four, plus room for an answer — and releases it when its response comes
    back, an error's included: ADK hands the after-hook what the error hook
    substituted for an exception, so one hook sees every call end. A response
    carrying no usage was never billed — substituted, or refused before the
    call — and is attempted, not completed; a blocked answer carries the usage
    the provider charged, and counts. The refusal is the redaction plugin's shape: an error
    response the lane ends with, under its own name, so the run degrades and
    reports what was found. A ceiling ends the spending, never the report.
    """

    def __init__(self, name: str = "usage_ledger", ceiling: int | None = None) -> None:
        super().__init__(name=name)
        self.ceiling = ceiling
        self.rows: dict[str, dict[str, int]] = {}
        self.reserved: dict[str, int] = {}  # agent name -> tokens reserved for the call it has in flight

    def _row(self, context: Any) -> dict[str, int]:
        return self.rows.setdefault(context.agent_name, {"attempted": 0, "calls": 0, "tokens": 0})

    @property
    def spent(self) -> int:
        return sum(r["tokens"] for r in self.rows.values())

    @staticmethod
    def _estimate(llm_request: Any) -> int:
        """What a request will cost, before it is sent: its text over four, plus an answer's worth."""
        chars = len(str(llm_request.config.system_instruction or ""))
        chars += sum(len(part.text) for part in _text_parts(llm_request))
        return chars // 4 + ANSWER_ALLOWANCE

    @override
    async def before_model_callback(self, *, callback_context: Any, llm_request: Any) -> LlmResponse | None:
        self._row(callback_context)["attempted"] += 1  # a call that never returns is attempted, not billed
        if self.ceiling is None:
            return None
        estimate, in_flight = self._estimate(llm_request), sum(self.reserved.values())
        if self.spent + in_flight + estimate > self.ceiling:
            return LlmResponse(
                error_code="TOKEN_CEILING",
                error_message=(
                    f"the ceiling of {self.ceiling:,} tokens would be passed: {self.spent:,} spent, "
                    f"{in_flight:,} in flight, this call about {estimate:,}; concluding with what was found"
                ),
            )
        self.reserved[callback_context.agent_name] = estimate
        return None

    @override
    async def after_model_callback(self, *, callback_context: Any, llm_response: Any) -> LlmResponse | None:
        self.reserved.pop(callback_context.agent_name, None)
        usage = llm_response.usage_metadata
        if usage is None:  # substituted for an exception, or refused before the call: over, never billed
            return None
        row = self._row(callback_context)
        row["calls"] += 1
        # The provider's own total when it reports one; the parts this code knows to read otherwise.
        prompt, candidates = usage.prompt_token_count or 0, usage.candidates_token_count or 0
        row["tokens"] += usage.total_token_count or (prompt + candidates)
        return None

    def render(self) -> str:
        calls = sum(r["calls"] for r in self.rows.values())
        attempted = sum(r["attempted"] for r in self.rows.values())
        lines = [f"- spend: {calls} model call(s) completed of {attempted} attempted, {self.spent:,} tokens"]
        lines += [
            f"  - `{name}`: {r['calls']} call(s), {r['tokens']:,} tokens" for name, r in sorted(self.rows.items())
        ]
        if self.ceiling is not None:
            lines.append(f"- ceiling: {self.ceiling:,} tokens")
        return "\n".join(lines)
