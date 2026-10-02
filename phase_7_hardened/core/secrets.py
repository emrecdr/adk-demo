"""Known credential shapes: scrubbed from everything a model sees, and found by code before any model runs.

`gate_findings` is the other half of redaction. Measured on the Copilot arm:
with the plugin scrubbing every prompt, no lane reported the hard-coded AWS
key, because no lane ever saw it. A secret must therefore be found by code,
from the diff itself, by a gate that runs before the lanes — and that is why
the lanes judge evidence rather than hunt for it. Shape-based: the gate reads
added lines one at a time, so a private key is found by its header, and the
redaction, reading whole text, hides its block. Measured before this table: 6
of 20 common shapes found, and `token = get_token(request)` a hard-coded-
credential blocker; a value is a secret when it is quoted, or when a `.env` or
YAML line holds it with a digit, never when code names, reads or calls it.
"""

from __future__ import annotations

import re
from typing import Any

from .findings import Finding

#: The gate's name in the report; the deterministic half always comes first.
GATE = "gate_secrets"

#: (kind, pattern, replacement).
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


def scrub_value(value: Any) -> tuple[Any, int]:
    """`scrub` applied to every string inside a tool result, however nested."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        out, total = {}, 0
        for key, item in value.items():
            out[key], count = scrub_value(item)
            total += count
        return out, total
    if isinstance(value, list):
        out, total = [], 0
        for item in value:
            scrubbed, count = scrub_value(item)
            out.append(scrubbed)
            total += count
        return out, total
    return value, 0


def gate_findings(files: list[dict]) -> list[Finding]:
    """The deterministic half: every known secret shape on a line each file's change ADDED, found before any model ran.

    Reads `collect_evidence`'s structured files — each carries its added
    lines, numbered from git's own hunk headers — not the rendered block the
    lanes read: the block is capped for a model's sake, and a credential past
    the cap must still be found. A gate finding is exact where a lane's is a
    guess.
    """
    findings = []
    for entry in files:
        for line, text in entry["added"]:
            # One finding a line, the first shape that fits: a line holding a key is one finding, whatever else fits.
            if kind := next((kind for kind, pattern, _ in _PATTERNS if pattern.search(text)), None):
                findings.append(
                    Finding(
                        file=entry["path"],
                        line=line,
                        severity="blocker",
                        title=f"hard-coded credential ({kind})",
                        evidence=scrub(f"+{text}")[0],  # the report is read in a terminal and pasted into chats
                        suggestion="Read it from the environment or a secret store, remove it from history, and "
                        "rotate it.",
                    )
                )
    return findings
