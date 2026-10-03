"""A project's own rule: a line that tries to instruct the reviewing model is a finding, never an order.

A file rule, read as a model reads text. Each added line is NFKC-normalised, so a full-width letter is the letter,
and stripped of every format character, so a zero-width space or a soft hyphen inside a word hides nothing; then
it is read joined with the next two lines, up to a blank one, their comment leaders and quotes dropped at the joins,
since a directive wraps as any sentence does and no sentence spans a paragraph break. Measured offline against the
one-line regex this replaced: a soft hyphen
inside `ignore`, full-width letters, a directive wrapped over two added lines and a docstring declaring an override
of the system each passed it; each is a finding here, on the added line where the shape starts.
"""

from __future__ import annotations

import re
import unicodedata

from ..core.rules import ChangedFile, FileRule

#: The shapes such text takes, each needing more than a word: code and comments pass, accept, ignore and approve
#: things all day, and a review is told to approve a change, forget its rules, take a new role, or answer nothing.
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
        r"\bsystem\s+override\b|\boverride\s+(?:the\s+)?(?:review(?:er)?|system)\b",
        r"\b(?:report|return|output|give|produce)\s+(?:zero|no|an?\s+empty(?:\s+list\s+of)?)\s+"
        r"(?:findings?|issues?|problems?|comments?)\b|\bempty\s+findings\s+list\b",
        r"\b(?:operator|administrator|admin|maintainer|owner|author)\s+(?:has|have)\s+(?:already\s+)?"
        r"(?:approved|authori[sz]ed|reviewed)\s+(?:this|the)\s+(?:module|file|change|pr|pull\s+request|branch|code|diff)\b",
    )
)
#: What leads a comment or a quoted line, dropped where lines are joined: `#`, `//`, `*`, `>`, quotes, a backslash.
_LEADERS = " \t#*/;>!-\"'`\\"
#: How many lines after an added one are read with it, up to a blank line: a sentence wraps once or twice.
JOINED_LINES = 2
#: A phrase is read this far: a directive is short, and a minified line is not a sentence.
PHRASE_MAX_CHARS = 300


def plain(line: str) -> str:
    """The line as a model reads it: NFKC-normalised, every format character gone, whitespace one space."""
    text = unicodedata.normalize("NFKC", line)
    return " ".join("".join(ch for ch in text if unicodedata.category(ch) != "Cf").split())


class ReviewerInstructions(FileRule):
    """The diff is data the lanes judge, never an order they take; this names the lines that try. Any file: such
    text sits in comments, strings and documents alike. A fixture that holds the words on purpose is a finding too,
    below the bar, for a person to wave through."""

    id = "reviewer-instructions"
    severity = "major"
    title = "text that tries to instruct the reviewing model"
    fix = "Remove it: a review is decided from the code. A test that needs these words as data keeps them in a fixture."

    def check(self, file: ChangedFile) -> list[tuple[int | None, str]]:
        # Only what is read, as a model reads it: each added line and the lines that may join it, not the whole file.
        read = {i for n in file.added for i in range(n - 1, n + JOINED_LINES) if 0 <= i < len(file.lines)}
        lines = {i: plain(file.lines[i]) for i in read}
        covered: dict[int, int] = {}  # each shape, and the last line a phrase that showed it reached: read once
        found: list[tuple[int | None, str]] = []
        for number in sorted(file.added):
            if not lines[number - 1]:  # a blank line starts no sentence
                continue
            phrase, last = _joined(lines, number, len(file.lines))
            shown = [
                k for k, directive in enumerate(_DIRECTIVES) if number > covered.get(k, 0) and directive.search(phrase)
            ]
            for k in shown:
                covered[k] = last
            if shown:
                found.append((number, f"+{file.line(number)}"))
        return found


def _joined(lines: dict[int, str], number: int, total: int) -> tuple[str, int]:
    """Line `number` read with the next `JOINED_LINES` lines of the `total`, up to a blank one, their leaders dropped
    at the joins, and the number of the last line read; `lines` holds them plain, by index."""
    parts, last = [lines[number - 1]], number
    for index in range(number, min(number + JOINED_LINES, total)):
        if not lines[index]:  # a paragraph break: no sentence wraps across it
            break
        parts.append(lines[index].strip(_LEADERS))
        last = index + 1
    return " ".join(parts)[:PHRASE_MAX_CHARS], last
