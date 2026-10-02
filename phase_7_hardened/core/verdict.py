"""Everything between the lanes' raw answers and a verdict: grounding, folding, deciding. Pure, and counted.

Every narrowing is counted and printed, including zeros, so a reader can see
what was removed and why. Nothing here calls a model or a process.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache

from .findings import RANK, Finding, Review
from .secrets import scrub
from .text import squash

EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, EXIT_DEGRADED = 0, 1, 2, 3
#: Where the diff places a finding: its first and last line, None when a line is not known.
Lines = tuple[int | None, int | None] | None


@dataclass
class Sourced:
    """A finding and where it came from: a gate's name, or a lane's state key."""

    source: str
    finding: Finding
    #: The first and last line the diff places it on: a gate's one line, a lane's quote where grounding found it.
    lines: Lines = None


@dataclass
class Outcome:
    """What post-processing decided, in one place, so the verdict and the report read the same numbers."""

    kept: list[Sourced] = field(default_factory=list)
    dropped: list[Sourced] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # source -> why that lane, gate or rule could not look
    unread: dict[str, str] = field(default_factory=dict)  # path -> why no check that ran read it whole
    folded: list[tuple[Sourced, Sourced]] = field(default_factory=list)  # a finding, and the one it folded into
    redacted: int = 0
    verified: bool = False  # `--verify` ran
    refuted: list[tuple[Sourced, str]] = field(default_factory=list)  # dropped on the verifier's say-so, with why
    unverified: list[tuple[Sourced, str]] = field(default_factory=list)  # the verifier could not judge; kept, with why


@lru_cache(maxsize=512)
def as_seen(text: str) -> str:
    """Text the way a lane saw it and quotes it: secrets redacted, diff markers gone, whitespace flat.

    Measured on Copilot with the drops named: a lane quoted two added lines
    without their `+` markers and was dropped; another quoted the redaction
    placeholders it had been shown and was dropped. Both were grounded — in
    the text the model read, not in the raw diff. Cached: the same diff is the
    haystack for every lane, and every finding is looked at twice.
    """
    redacted, _count = scrub(text)
    stripped = [line[1:] if line[:1] in "+- " else line for line in redacted.splitlines()]
    return squash("\n".join(stripped))


@lru_cache(maxsize=512)
def seen_lines(text: str, markers: bool = True) -> tuple[str, ...]:
    """`as_seen` line by line, with every space gone rather than flattened: secrets redacted, a diff marker gone,
    blank lines left out. Measured on Gemini: a lane quoted three whole lines with the breaks between them lost,
    joined by a space or by nothing, so where a line ends is read off the file, never off the quote. `markers`
    off keeps a line's leading `+` or `-`: in a quote it may be the line's own text, a YAML item's dash."""
    redacted, _count = scrub(text)
    return _flat(redacted, markers)


def _flat(text: str, markers: bool = True) -> tuple[str, ...]:
    """Each line of `text` with its diff marker gone and every space gone, blank lines left out; nothing redacted."""
    lines = ("".join((line[1:] if markers and line[:1] in "+- " else line).split()) for line in text.splitlines())
    return tuple(line for line in lines if line)


def _whole_lines(quote: str, lines: tuple[str, ...]) -> Iterator[tuple[int, int]]:
    """Each place `quote` starts and ends as a run of consecutive `lines`, each whole: it starts where one begins and
    ends where one ends."""
    for start in range(len(lines)):
        run, end = "", start
        for end in range(start, len(lines)):
            run += lines[end]
            if len(run) >= len(quote):
                break
        if run == quote:
            yield start, end


def drop_ungrounded(review: Review, quotable: dict[str, list[tuple[int, str]]]) -> tuple[list[Finding], list[Finding]]:
    """Split findings into those that quote their own file's diff — whole lines, in order, as the lane saw them,
    whatever whitespace joined them — and the rest. `quotable` is each changed file's hunk lines with their line
    numbers, from `collect_evidence`.

    Measured with the rule it replaced, a substring of the whole rendered
    block: a `### <path>` heading, the fence, a hunk header, git's
    `diff --git` line and the one word `import` were each grounded, and a
    finding's `file` was never read. The radius had been one member of that
    class: out of the block, it no longer carries the safety, this rule does.
    Measured live on both arms against the planted branch: every lane quote
    is grounded by it. A kept finding's line is where its quote starts, read
    off the diff: measured live on Copilot, the lanes named a wrong line for
    4 of 5 findings.
    """
    kept: list[Finding] = []
    dropped: list[Finding] = []
    for finding in review.findings:
        if (where := where_quoted(finding, quotable)) is None:
            dropped.append(finding)
        else:
            kept.append(finding.model_copy(update={"line": where[0]}))
    return kept, dropped


def where_quoted(finding: Finding, quotable: dict[str, list[tuple[int, str]]]) -> Lines:
    """The first and last line of `finding`'s quote in its own file's diff, where it is whole lines there, in order,
    as the lane saw them; `(None, None)` where the redaction joined lines, so no line is named rather than a wrong
    one; None where the diff does not bear the quote out."""
    numbered = quotable.get(finding.file, [])
    lines = seen_lines("\n".join(raw for _number, raw in numbered))
    # Read both ways: measured, `- run: …` and `++i;` quoted as the file has them lost their first character.
    quotes = {"".join(seen_lines(finding.evidence, markers)) for markers in (True, False)}
    runs = {run for quote in quotes for run in _whole_lines(quote, lines)}
    if not runs:
        return None
    # Each seen line's number, counted unredacted: a redaction never adds or removes a line of its own, and line by
    # line through the cache it crowded out the files' own text. Where the redaction joined lines, a private key's
    # block one line as the lane saw it, the counts differ.
    numbers = [number for number, raw in numbered for _line in _flat(raw)]
    if len(numbers) != len(lines):
        return None, None
    # A short quote can stand in several places: measured by review, `return None` at lines 2 and 22, a lane naming
    # 22 was placed at 2. The diff decides where a quote can stand; the lane's line only picks among those places,
    # the first where it named none and on a tie.
    start, end = min(runs, key=lambda run: (abs(numbers[run[0]] - finding.line) if finding.line else 0, run))
    return numbers[start], numbers[end]


def _overlaps(x: str, x_lines: Lines, y: str, y_lines: Lines) -> bool:
    """Two findings about the same lines. Where the diff places both, one's lines hold the other's: measured by
    review, folded by text alone, a minor quoting `return None` at line 2 held a blocker whose quote ends in another
    `return None` at line 6, and took it. Where either is not placed, one quote, neither empty, contains the other."""
    if x_lines and y_lines and None not in (*x_lines, *y_lines):
        (a, b), (c, d) = x_lines, y_lines
        return (a <= c and d <= b) or (c <= a and b <= d)
    return bool(x and y) and (x in y or y in x)


def to_verify(lanes: list[Sourced], gates: list[Sourced]) -> list[Sourced]:
    """The lane findings worth a verifier: all but those that only say again what a gate found — a gate's quote
    and its own overlap, in one file, and the gate's reading is at least as severe, so the fold keeps the gate's
    whatever were said of the lane's. The fold still folds them, as it would without `--verify`. Each gate's quote
    is normalised once and compared only within its file, as `dedupe` does: normalised per pair, a thousand of
    ruff's findings in one file and thirty lane findings measured 147 ms against 7 ms."""
    said: dict[str, list[tuple[int, str, Lines]]] = {}  # file -> (rank, quote as seen, lines) of each gate finding
    for gate in gates:
        seen = as_seen(gate.finding.evidence)
        said.setdefault(gate.finding.file, []).append((RANK[gate.finding.severity], seen, gate.lines))
    asked: list[Sourced] = []
    for item in lanes:
        rank, seen = RANK[item.finding.severity], as_seen(item.finding.evidence)
        here = said.get(item.finding.file, ())
        if not any(at >= rank and _overlaps(seen, item.lines, quote, lines) for at, quote, lines in here):
            asked.append(item)
    return asked


def dedupe(kept: list[Sourced]) -> tuple[list[Sourced], list[tuple[Sourced, Sourced]]]:
    """One finding per span of the diff: the most severe reading first, whole, the first source on a tie.

    Measured on Copilot: three lanes reported the shell finding, each quoting a
    different span of the same two lines, and the report carried it three
    times. Overlapping quotes in one file are one finding — across lanes, and
    across gates. Whole, not merged: measured with ruff in front of the lanes,
    keeping the first title at the higher severity made "line too long" a
    blocker. Most severe first, and each finding kept only if it overlaps none
    already kept: measured live, a lane's blocker quoting a whole function
    replaced the one ruff finding it was compared with, and left the other,
    on the next line, standing beside it. The findings keep the order they came in.
    Each quote is normalised once and compared only within its file:
    the lint gate reads whole files, so a test-heavy branch brings findings by
    the hundred per file, and comparing every pair through `as_seen`'s cache
    measured 689 ms at 1,000 findings against 32 ms this way; most severe
    first costs what the order before it did, 12 ms each on a thousand.
    """
    held: dict[str, list[tuple[int, str, Lines]]] = {}  # file -> each kept finding's index, quote as seen, lines
    into: dict[int, int] = {}  # a folded finding's index -> the index of the finding it folded into
    # `sorted` is stable: on a tie the first source comes first.
    for index in sorted(range(len(kept)), key=lambda i: -RANK[kept[i].finding.severity]):
        item = kept[index]
        seen, here = as_seen(item.finding.evidence), held.setdefault(item.finding.file, [])
        survivor = next((at for at, quote, lines in here if _overlaps(seen, item.lines, quote, lines)), None)
        if survivor is None:
            here.append((index, seen, item.lines))
        else:
            into[index] = survivor
    return [item for index, item in enumerate(kept) if index not in into], [
        (kept[i], kept[into[i]]) for i in sorted(into)
    ]


def ungrounded_at(outcome: Outcome, fail_on: str) -> int:
    """How many findings at or above `fail_on` were dropped for a quote the diff does not bear out."""
    return sum(RANK[item.finding.severity] >= RANK[fail_on] for item in outcome.dropped)


def decide(outcome: Outcome, fail_on: str) -> tuple[str, int]:
    """The verdict and the exit code, from the findings that survived and the lanes that did not.

    Only kept findings count: one dropped for evidence that is not in the diff
    must not decide the build. A failed lane is a hole, and so is a file no lane read whole, and so is a finding
    at the bar that no quote bears out, since a real blocker dropped would approve: a hole never approves.
    """
    if outcome.errors or outcome.unread or ungrounded_at(outcome, fail_on):
        return "DEGRADED", EXIT_DEGRADED
    worst = max((RANK[item.finding.severity] for item in outcome.kept), default=0)
    return ("REQUEST_CHANGES", EXIT_FINDINGS) if worst >= RANK[fail_on] else ("APPROVED", EXIT_CLEAN)
