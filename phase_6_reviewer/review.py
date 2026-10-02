"""The command line: evidence first, lanes judge, code decides.

    uv run python -m phase_6_reviewer.review <repo> --base main --head feature/payments

1. The central `.env` is loaded by path — no ADK loader runs here — and the
   arm's readiness is checked before anything is spent, so a typo in `.env`
   is a sentence and an exit code, never a traceback from inside the run.
2. `collect_evidence` runs git in plain Python. No model has been called yet.
   The secrets gate reads every file's whole diff here, by code.
3. Session state is seeded with the diff and the lanes-only graph runs
   under the App that carries the three plugins, through a `Runner`.
4. Each lane's `Review` is read back from state; a finding whose evidence is
   not in the diff as the lane saw it is dropped and named; the gate's
   findings — which the redaction plugin then hid from every lane — join
   them; a finding about the same lines as one the gate or another lane
   made (or, unplaced, whose quote contains or sits inside its quote) is
   folded into it, counted; the
   verdict and the exit code are computed here, by code. A lane that failed
   — its provider raised or timed out, or the redaction plugin refused the
   call — ended as its own error event, so the other lanes finished
   regardless; it is named with the reason and the run is degraded: exit 3,
   never an approval. The bar is `blocker` by
   default: a lane's severity is a model's judgement and
   varies between runs, so a build fails on what must not merge, while
   majors and minors stay in the report for a person.
5. A markdown report, ending with what the run cost.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import tempfile
import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google.adk.apps.app import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from .config import require_ready, serving
from .lanes import LANE_NAMES, Finding, Review, lane_review, state_key
from .plugins import REASON_MAX_CHARS, RedactSecretsPlugin, UsageLedger, scan_secrets, scrub
from .tools import collect_evidence

ROOT = Path(__file__).resolve().parents[1]
#: The repository `scripts/make_demo_repo.py` builds, spelled the way it spells it — a copy, because a phase
#: folder runs alone — so the command needs no path on stage.
DEMO_REPO = Path(tempfile.gettempdir()) / "adk-demo-repo"
RANK = {"minor": 1, "major": 2, "blocker": 3}
EXIT_CLEAN, EXIT_FINDINGS, EXIT_USAGE, EXIT_DEGRADED = 0, 1, 2, 3
GATE = "gate_secrets"
#: Report order: the deterministic gate first, then the lanes in table order.
SOURCES = (GATE, *(state_key(name) for name in LANE_NAMES))
#: A quote is read by a person, who has its file and line for the rest. A gate quotes the whole added line, and a
#: minified one ran to 200,000 characters. Cut after the scrub, so no cut halves a credential past its pattern.
EVIDENCE_MAX_CHARS = 400


@dataclass
class Sourced:
    """A finding and where it came from: the gate, or a lane's state key."""

    source: str
    finding: Finding
    #: The first and last line the diff places it on: a gate's one line, a lane's quote where grounding found it.
    lines: tuple[int | None, int | None] | None = None


@dataclass
class Outcome:
    """What post-processing decided, in one place, so the verdict and the report read the same numbers."""

    kept: list[Sourced] = field(default_factory=list)
    dropped: list[Sourced] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # source -> why that lane failed
    unread: dict[str, str] = field(default_factory=dict)  # path -> why no lane read it whole
    folded: int = 0
    redacted: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review", description="Review a branch: gates in Python, lanes judge, code decides."
    )
    parser.add_argument("repo", nargs="?", default=str(DEMO_REPO), help="path to the repository (default: the demo)")
    parser.add_argument("--base", default="main", help="the branch the change will be merged into")
    parser.add_argument("--head", required=True, help="the branch under review")
    parser.add_argument(
        "--fail-on",
        choices=list(RANK),
        default="blocker",
        help="exit 1 at or above this severity; blocker by default; majors and minors stay in the report",
    )
    return parser


def _squash(text: str) -> str:
    return " ".join(text.split())


#: What a terminal runs or reorders: escape sequences, C0 and C1 controls (U+009B is `ESC [` in one character), and
#: the marks that turn the text after them around (U+202E and its kin).
_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _one_line(text: str) -> str:
    """Model prose as one markdown line: escape sequences and control characters out, whitespace flat.

    The report is read in a terminal and pasted into chats. Measured: a title
    holding a newline forged a second `## Verdict` heading, a newline in a
    suggestion forged a bullet, and `ESC[2J` cleared the terminal. A credential
    in it is hidden too: the report never prints one. Presentation only: grounding
    (`_as_seen`) squashes whitespace and nothing else, so what counts as
    grounded cannot move when the report's safety rule does.
    """
    return _squash(_CONTROL.sub(" ", scrub(text)[0]))


#: A CI runner's command in its log: Azure runs `##vso[` and GitHub `##[` anywhere in a line, GitHub across invisible
#: characters between them (measured on .NET), so any non-ASCII run counts. GitHub's `::` counts only opening a line,
#: and no printed line opens with the branch's text.
_RUNNER_COMMAND = re.compile(r"#[^ -~]*#[^ -~]*(?:vso)?(?=\[)")


def _inert(text: str) -> str:
    """`text` with each CI runner's command opener broken by a space, `##vso [`, and each HTML comment's, `<! --`,
    which hid what lay between two paths wherever the report renders as markdown: paths and quotes are the branch's."""
    return _RUNNER_COMMAND.sub(r"\g<0> ", text).replace("<!--", "<! --")


def _cut_at(text: str, limit: int) -> str:
    """`text` cut at `limit` characters with the cut named, as every cap in this demo names its cut."""
    return text if len(text) <= limit else f"{text[:limit]} [… cut at {limit:,} characters]"


def _code_span(text: str) -> str:
    """`text` as a markdown code span fenced to beat its own backticks: a lane quotes source, and source has them."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


@lru_cache(maxsize=512)
def _as_seen(text: str) -> str:
    """Text the way a lane saw it and quotes it: secrets redacted, diff markers gone, whitespace flat.

    Measured on Copilot with the drops named: a lane quoted two added lines
    without their `+` markers and was dropped; another quoted the redaction
    placeholders it had been shown and was dropped. Both were grounded — in
    the text the model read, not in the raw diff. Cached: the same diff is the
    haystack for every lane, and every finding is looked at twice.
    """
    redacted, _count = scrub(text)
    stripped = [line[1:] if line[:1] in "+- " else line for line in redacted.splitlines()]
    return _squash("\n".join(stripped))


@lru_cache(maxsize=512)
def _seen_lines(text: str, markers: bool = True) -> tuple[str, ...]:
    """`_as_seen` line by line, with every space gone rather than flattened: secrets redacted, a diff marker gone,
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
    finding's `file` was never read. Measured live on both arms against the
    planted branch: every lane quote is grounded by it. A kept finding's line
    is where its quote starts, read off the diff: measured live on Copilot,
    the lanes named a wrong line for 4 of 5 findings.
    """
    kept: list[Finding] = []
    dropped: list[Finding] = []
    for finding in review.findings:
        if (where := where_quoted(finding, quotable)) is None:
            dropped.append(finding)
        else:
            kept.append(finding.model_copy(update={"line": where[0]}))
    return kept, dropped


def where_quoted(finding: Finding, quotable: dict[str, list[tuple[int, str]]]) -> tuple[int | None, int | None] | None:
    """The first and last line of `finding`'s quote in its own file's diff, where it is whole lines there, in order,
    as the lane saw them; `(None, None)` where the redaction joined lines, so no line is named rather than a wrong
    one; None where the diff does not bear the quote out."""
    numbered = quotable.get(finding.file, [])
    lines = _seen_lines("\n".join(raw for _number, raw in numbered))
    # Read both ways: measured, `- run: …` and `++i;` quoted as the file has them lost their first character.
    quotes = {"".join(_seen_lines(finding.evidence, markers)) for markers in (True, False)}
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


def _same_lines(x: tuple[int | None, int | None] | None, y: tuple[int | None, int | None] | None) -> bool | None:
    """Whether one of two placed spans holds the other; None where either is not placed, for the quotes to decide.
    Measured by review: folded by text alone, a minor quoting `return None` at line 2 held a blocker whose quote
    ends in another `return None` at line 6, and took it."""
    if not (x and y) or None in (*x, *y):
        return None
    return (x[0] <= y[0] and y[1] <= x[1]) or (y[0] <= x[0] and x[1] <= y[1])


def _same_finding(a: Sourced, b: Sourced) -> bool:
    """Two findings about the same lines: same file, and one's lines hold the other's, or, where either is not
    placed, one quote contains the other."""
    if a.finding.file != b.finding.file:
        return False
    if (placed := _same_lines(a.lines, b.lines)) is not None:
        return placed
    x, y = _as_seen(a.finding.evidence), _as_seen(b.finding.evidence)
    return bool(x and y) and (x in y or y in x)


def dedupe(kept: list[Sourced]) -> tuple[list[Sourced], int]:
    """One finding per span of the diff: the first source keeps it, at the higher severity.

    Measured on Copilot: three lanes reported the shell finding, each quoting a
    different span of the same two lines, and the report carried it three
    times. Overlapping quotes in one file are one finding. Counted, like every
    other narrowing here, so a reader can see how much overlap there was.
    """
    out: list[Sourced] = []
    folded = 0
    for item in kept:
        match = next((held for held in out if _same_finding(held, item)), None)
        if match is None:
            out.append(item)
            continue
        folded += 1
        if RANK[item.finding.severity] > RANK[match.finding.severity]:
            match.finding.severity = item.finding.severity
    return out, folded


def _ungrounded_at(outcome: Outcome, fail_on: str) -> int:
    """How many findings at or above `fail_on` were dropped for a quote the diff does not bear out."""
    return sum(RANK[item.finding.severity] >= RANK[fail_on] for item in outcome.dropped)


def decide(outcome: Outcome, fail_on: str) -> tuple[str, int]:
    """The verdict and the exit code, from the findings that survived and the lanes that did not.

    Only kept findings count: one dropped for evidence that is not in the diff
    must not decide the build. A failed lane is a hole, and so is a file no lane read whole, and so is a finding
    at the bar that no quote bears out, since a real blocker dropped would approve: a hole never approves.
    """
    if outcome.errors or outcome.unread or _ungrounded_at(outcome, fail_on):
        return "DEGRADED", EXIT_DEGRADED
    worst = max((RANK[item.finding.severity] for item in outcome.kept), default=0)
    return ("REQUEST_CHANGES", EXIT_FINDINGS) if worst >= RANK[fail_on] else ("APPROVED", EXIT_CLEAN)


async def judge(app: App, diff: str) -> tuple[dict, dict[str, str]]:
    """Run the lanes-only graph over a session seeded with the diff; return the state afterwards and, per
    lane, the reason to give if it wrote nothing: its own error event, else the engine's failure, else the fact.

    A lane that failed — its provider raised or timed out, or the redaction
    plugin refused the call — ends with an error event under its own name
    (`ReportProviderErrors`) and its `output_key` unwritten; the graph goes
    on and every other lane finishes. Anything that still escapes the engine
    is caught here as the run's failure, so what was found is reported and
    what failed is named — never a traceback and Python's exit 1, which is
    this command's code for "findings found".
    """
    runner = InMemoryRunner(app=app)
    session_args = {"app_name": app.name, "user_id": "reviewer", "session_id": "run"}
    await runner.session_service.create_session(**session_args, state={"diff": diff})
    message = types.UserContent("review")
    by_lane: dict[str, str] = {}
    run_failure: str | None = None
    try:
        async for event in runner.run_async(user_id="reviewer", session_id="run", new_message=message):
            if event.error_code:
                by_lane[event.author] = f"{event.error_code}: {event.error_message}"
    except Exception as exc:  # noqa: BLE001 -- the engine itself; a lane's own failure never gets here
        run_failure = f"{type(exc).__name__}: {exc}"
    session = await runner.session_service.get_session(**session_args)
    reasons = {
        key: by_lane.get(key) or run_failure or "the lane produced no output" for key in map(state_key, LANE_NAMES)
    }
    return dict(session.state), reasons


def gate_findings(files: list[dict]) -> list[Finding]:
    """The deterministic half: secrets found in every file's whole diff by code, before any model ran."""
    return [
        Finding(
            file=hit.file,
            line=hit.line,
            severity="blocker",
            title=f"hard-coded credential ({hit.kind})",
            evidence=scrub(hit.evidence)[0],  # the report is read in a terminal and pasted into chats
            suggestion="Read it from the environment or a secret store, remove it from history, and rotate it.",
        )
        for hit in scan_secrets(files)
    ]


def postprocess(state: dict, evidence: dict, redacted: int, reasons: dict[str, str], gates: list[Sourced]) -> Outcome:
    """Everything between the lanes' raw answers and a verdict, each narrowing counted; the gate's findings first."""
    outcome = Outcome(redacted=redacted, unread={f["path"]: f["unread"] for f in evidence["files"] if f["unread"]})
    outcome.kept += gates
    quotable = {f["path"]: f["quotable"] for f in evidence["files"]}
    for name in LANE_NAMES:
        key = state_key(name)
        review = lane_review(state, name, reasons[key])
        if isinstance(review, str):
            outcome.errors[key] = review
            continue
        kept, dropped = drop_ungrounded(review, quotable)
        outcome.kept += [Sourced(key, f, where_quoted(f, quotable)) for f in kept]
        outcome.dropped += [Sourced(key, f) for f in dropped]
    outcome.kept, outcome.folded = dedupe(outcome.kept)
    return outcome


def _as_resolved(name: str, ref: str) -> str:
    """A name as given, and the tag it resolved through when it is one: a fork's tag `origin/main`, with no such
    branch fetched, once stood in for the branch unseen."""
    return f"{name} (the tag {ref})" if ref.startswith("refs/tags/") else name


def render(
    pre: dict,
    files: list[dict],
    outcome: Outcome,
    verdict: str,
    ledger: UsageLedger,
    fail_on: str,
    model: str,
) -> str:
    lines = [
        f"# Review: {pre['head']} against {pre['base']}",
        "",
        f"- repository   {pre['repo']}",
        f"- branch       {_as_resolved(pre['head'], pre.get('head_ref', ''))} @ {pre['head_sha'][:9]}",
        f"- against      {_as_resolved(pre['base'], pre.get('base_ref', ''))} @ {pre['base_sha'][:9]}",
        f"- merge-base   {pre['merge_base'][:9]}",
        f"- model        {model}",
        f"- changed      {len(files)} file(s): " + ", ".join(_code_span(_one_line(f["path"])) for f in files),
        *(f"- not read     {_code_span(_one_line(path))}: {why}" for path, why in outcome.unread.items()),
        "",
        f"## Verdict: {verdict}",
        "",
    ]
    for source in SOURCES:
        findings = [item.finding for item in outcome.kept if item.source == source]
        failed = outcome.errors.get(source)
        lines.append(f"### {source}" + (f" — FAILED: {_cut_at(_one_line(failed), REASON_MAX_CHARS)}" if failed else ""))
        for f in findings:
            where = _one_line(f"{f.file}:{f.line}" if f.line else f.file)  # a path is the branch's text
            lines += [
                f"- **{f.severity}** {_one_line(f.title)} ({where})",
                f"  - evidence: {_code_span(_cut_at(_one_line(f.evidence), EVIDENCE_MAX_CHARS))}",
                f"  - fix: {_one_line(f.suggestion)}",
            ]
        if not findings and not failed:
            lines.append("- no findings")
        lines.append("")
    lines.append(f"- findings dropped for evidence not in the diff: {len(outcome.dropped)}")
    if severe := _ungrounded_at(outcome, fail_on):
        lines.append(f"  - {severe} at or above `--fail-on {fail_on}`: not approved until a person reads them")
    # Named, so a reader can tell a lane that invented a quote from one that merely paraphrased.
    lines += [
        f"  - `{item.source}`: {_one_line(item.finding.title)} — quoted "
        f"{_code_span(_cut_at(_one_line(item.finding.evidence), 120))}"
        for item in outcome.dropped
    ]
    lines += [
        f"- duplicates across lanes folded into one finding: {outcome.folded}",
        f"- secrets redacted before any model call: {outcome.redacted}",
        ledger.render(),
        "",
    ]
    return _inert("\n".join(lines))  # once over the whole: no two fields side by side spell one


def _say(sentence: str) -> None:
    """A sentence on stderr, made safe as the report's prose is: git's or an exception's words can be the branch's."""
    print(f"review: {_inert(_one_line(sentence))}", file=sys.stderr)


def _review(argv: list[str] | None = None) -> int:
    try:
        load_dotenv(ROOT / ".env")
    except UnicodeDecodeError:
        _say("the central .env is not UTF-8; save it as UTF-8 (Windows PowerShell 5.1's `>` writes UTF-16)")
        return EXIT_USAGE
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    args = build_parser().parse_args(argv)
    if (why := require_ready()) is not None:
        _say(why)
        return EXIT_USAGE
    evidence = collect_evidence(args.repo, args.base, args.head)
    if evidence["status"] != "success":
        _say(evidence["error_message"])
        return EXIT_USAGE
    # By code, before any model runs; each on the one line it names.
    gates = [Sourced(GATE, f, (f.line, f.line)) for f in gate_findings(evidence["files"])]

    from .agent import build_app  # here, never at import: the chat graph it builds would raise on a misspelt arm

    app = build_app(chat=False)
    redactor = next(p for p in app.plugins if isinstance(p, RedactSecretsPlugin))
    ledger = next(p for p in app.plugins if isinstance(p, UsageLedger))
    state, reasons = asyncio.run(judge(app, evidence["diff"]))

    outcome = postprocess(state, evidence, redactor.redacted, reasons, gates)
    verdict, code = decide(outcome, args.fail_on)
    print(render(evidence["preflight"], evidence["files"], outcome, verdict, ledger, args.fail_on, serving()))
    return code


def main(argv: list[str] | None = None) -> int:
    """The command, with a last resort: an error nothing above named ends as one sentence and exit 3, a review that
    did not finish, never Python's own exit 1, which is the code for "a blocker was found". Measured before: errors
    found and named one at a time, six recorded in the design record and a seventh by review, each ended so."""
    try:
        return _review(argv)
    except Exception as exc:  # noqa: BLE001 -- a crash must never read as a verdict
        _say(f"the review did not finish: {type(exc).__name__}: {exc}")
        return EXIT_DEGRADED


if __name__ == "__main__":
    # Process-wide settings belong at the process boundary, once; `main` stays a function of its arguments.
    warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")  # ADK announces a flag on every tool declaration
    # ADK logs a failed node with its whole traceback through Python's last-resort stderr handler. The report
    # names the lane and the reason, so that logger gets a handler that prints nothing; configured logging
    # (an operator's basicConfig) still receives every record.
    logging.getLogger("google_adk").addHandler(logging.NullHandler())
    # genai warns, on every Gemini call ADK makes, that it would rather be called another way; the same handler.
    logging.getLogger("google_genai").addHandler(logging.NullHandler())
    raise SystemExit(main())
