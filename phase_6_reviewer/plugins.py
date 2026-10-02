"""Three plugins on the App, which no agent can opt out of — and the gate that makes the first one safe to have.

A callback is per agent and is where "this tool needs an allowlist" belongs. A
plugin is registered once on the `App` and applies to every agent, which is
where "we never send a credential to a provider", "we always know what a
run cost" and "a provider error is one lane's answer, not the graph's death"
belong. `@override` marks each hook as one ADK calls by keyword: a
misnamed parameter would build fine and fail on the first live call.

`scan_secrets` is the other half of redaction. Measured on the Copilot arm:
with the plugin scrubbing every prompt, no lane reported the hard-coded AWS
key, because no lane ever saw it. A secret must therefore be found by code,
before any model runs, from the diff itself, by a gate that runs before the lanes —
and that is why the lanes judge evidence rather than hunt for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, override

from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

#: Known credential shapes: (kind, pattern, replacement). The gate reads added lines one at a time, so a private key
#: is found by its header; the redaction reads whole text and hides the block. Shape-based: an unnamed high-entropy
#: token still passes. Measured before this table: 6 of 20 common shapes found, and `token = get_token(request)`,
#: `password = os.environ[...]` and `secret = settings.X` each a hard-coded-credential blocker.
#: The name a secret goes by, prefixed and suffixed as code spells it (`DB_PASSWORD`, `client_secret`, `SECRET_KEY`),
#: never inside a longer word: `tokenizer` names none.
_NAMED = r"(?:api[_-]?key|secret|token|passw(?:or)?d|pwd)(?:[_.-][\w.-]*)?"
#: Not a value but a stand-in for one: a template, a placeholder, or what an earlier shape already hid.
_STAND_IN = r"(?![$%{<]|\[REDACTED)"
_PATTERNS = (
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:aws_access_key_id]"),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)(aws_secret_access_key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9/+=]{40}"),
        r"\1[REDACTED:aws_secret_access_key]",
    ),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{80,})\b"),
        "[REDACTED:github_token]",
    ),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"), "[REDACTED:gitlab_token]"),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack_token]"),
    ("slack_webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/]+"), "[REDACTED:slack_webhook]"),
    ("stripe_key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,}"), "[REDACTED:stripe_key]"),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), "[REDACTED:google_api_key]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED:jwt]"),
    (
        "url_credentials",
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@\"']+:)" + _STAND_IN + r"[^\s@/\"']+(@)"),
        r"\1[REDACTED]\2",
    ),
    ("azure_account_key", re.compile(r"(?i)(AccountKey=)" + _STAND_IN + r"[A-Za-z0-9+/=]{20,}"), r"\1[REDACTED]"),
    (
        "private_key",  # the whole block where the text holds it, its header where a line is all there is
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
            r"(?:[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)?"
        ),
        "[REDACTED:private_key]",
    ),
    (
        "generic_secret",  # a named value in quotes: code, JSON, YAML
        re.compile(r"(?i)(" + _NAMED + r"[\"']?\s*[:=]\s*)([\"'])" + _STAND_IN + r"([^\"'\n]{6,})\2"),
        r"\1\2[REDACTED]\2",
    ),
    (
        "generic_secret",  # a named value unquoted, a `.env` or YAML line, holding a digit: code names, reads, calls
        re.compile(
            r"(?im)^([+ -]?\s*(?:export\s+)?[\w.-]*"
            + _NAMED
            + r"\s*[:=]\s*)(?=[^\s#]*\d)"
            + _STAND_IN
            + r"([^\s\"'#(\[][^\s\"'#()\[\]{}]{7,})\s*$"
        ),
        r"\1[REDACTED]",
    ),
)


def scrub(text: str) -> tuple[str, int]:
    """`text` with every known secret shape replaced, and how many were."""
    total = 0
    for _kind, pattern, replacement in _PATTERNS:
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total


@dataclass(frozen=True)
class SecretHit:
    file: str
    line: int | None
    kind: str
    evidence: str


def scan_secrets(files: list[dict]) -> list[SecretHit]:
    """Every known secret shape on a line each file's change ADDED, with its new line number.

    Reads `collect_evidence`'s structured files — each carries its added
    lines, numbered by `tools._added_lines` from git's own hunk headers —
    not the rendered block the lanes read: the block is capped for a model's
    sake, and a credential past the cap must still be found. A gate finding
    is exact where a lane's is a guess.
    """
    hits = []
    for entry in files:
        for line, text in entry["added"]:
            # One hit a line, the first shape that fits: a line holding a key is one finding, whatever else it matches.
            if kind := next((kind for kind, pattern, _ in _PATTERNS if pattern.search(text)), None):
                hits.append(SecretHit(file=entry["path"], line=line, kind=kind, evidence=f"+{text}"))
    return hits


def _scrub_value(value: Any) -> tuple[Any, int]:
    """`scrub` applied to every string inside a tool result, however nested."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        out, total = {}, 0
        for key, item in value.items():
            out[key], count = _scrub_value(item)
            total += count
        return out, total
    if isinstance(value, list):
        out, total = [], 0
        for item in value:
            scrubbed, count = _scrub_value(item)
            out.append(scrubbed)
            total += count
        return out, total
    return value, 0


#: A reason is read by a person: a verifier's prose, a raw exception that escaped the engine; 400 characters say it.
REASON_MAX_CHARS = 400


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
    line = " ".join((f"{code}: {message}" if code else message).split())
    if len(line) <= REASON_MAX_CHARS:
        return line
    return f"{line[:REASON_MAX_CHARS]} [… cut at {REASON_MAX_CHARS} characters]"


class RedactSecretsPlugin(BasePlugin):
    """Scrubs known secret shapes from every tool result and every outgoing request. Fail-closed."""

    def __init__(self, name: str = "redact_secrets") -> None:
        super().__init__(name=name)
        self.redacted = 0

    @override
    async def before_model_callback(self, *, callback_context: Any, llm_request: Any) -> LlmResponse | None:
        """Returning a response SKIPS the model call: if scrubbing fails, nothing unscrubbed is sent."""
        try:
            for content in llm_request.contents or []:
                for part in content.parts or []:
                    if part.text:
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
        scrubbed, count = _scrub_value(result)
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
    deadline (`config.REQUEST_TIMEOUT_S`) arrives here the same way.
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
    """Counts model calls and tokens per agent, so an expensive run does not look like a cheap one.

    A call that failed is attempted, never completed: ADK hands the after-hook
    the response `ReportProviderErrors` put in the exception's place, and a
    response carrying no usage was never billed, so it is not counted — a
    blocked answer carries the usage the provider charged, and is.
    """

    def __init__(self, name: str = "usage_ledger") -> None:
        super().__init__(name=name)
        self.rows: dict[str, dict[str, int]] = {}

    def _row(self, context: Any) -> dict[str, int]:
        return self.rows.setdefault(context.agent_name, {"attempted": 0, "calls": 0, "tokens": 0})

    @override
    async def before_model_callback(self, *, callback_context: Any, llm_request: Any) -> LlmResponse | None:
        self._row(callback_context)["attempted"] += 1  # a call that never returns is attempted, not billed
        return None

    @override
    async def after_model_callback(self, *, callback_context: Any, llm_response: Any) -> LlmResponse | None:
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
        tokens = sum(r["tokens"] for r in self.rows.values())
        lines = [f"- spend: {calls} model call(s) completed of {attempted} attempted, {tokens:,} tokens"]
        lines += [
            f"  - `{name}`: {r['calls']} call(s), {r['tokens']:,} tokens" for name, r in sorted(self.rows.items())
        ]
        return "\n".join(lines)
