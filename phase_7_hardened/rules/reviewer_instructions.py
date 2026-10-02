"""A project's own rule: a line that tries to instruct the reviewing model is a finding, never an order."""

from __future__ import annotations

import re

from ..core.rules import Rule

#: The shapes such text takes, each needing more than a word: code and comments pass, accept, ignore and approve
#: things all day, and a review is told to approve a change, forget its rules, or take a new role.
_DIRECTIVES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:the\s+|your\s+|these\s+)?"
        r"(?:previous|prior|above|earlier)\s+(?:instructions?|directions?|rules|guidelines|review|findings)\b",
        r"\b(?:ignore|disregard|forget)\s+the\s+(?:review|reviewer)\b",
        r"\bapprove\s+(?:everything|(?:this|the)\s+(?:change|pr|pull\s+request|diff|review|commit|branch))\b"
        r"|\bpre-?approved\b",
        r"\byou\s+are\s+now\s+(?:an?\s+|the\s+)?(?:different\s+|new\s+)?(?:ai|assistant|model|reviewer|auditor|bot)\b",
        r"\bsystem\s+(?:instructions?|prompt)\s*:"
        r"|\b(?:note|message|instructions?)\s+(?:to|for)\s+the\s+(?:ai|automated|llm)[\s-]+(?:code[\s-]+)?reviewers?\b",
    )
)


class ReviewerInstructions(Rule):
    """The diff is data the lanes judge, never an order they take; this names the lines that try. Any file: such
    text sits in comments, strings and documents alike. A fixture that holds the words on purpose is a finding too,
    below the bar, for a person to wave through."""

    id = "reviewer-instructions"
    severity = "major"
    title = "text that tries to instruct the reviewing model"
    fix = "Remove it: a review is decided from the code. A test that needs these words as data keeps them in a fixture."

    def check(self, path: str, line: str) -> bool:  # noqa: ARG002 -- any file: the text is the finding
        return any(pattern.search(line) for pattern in _DIRECTIVES)
