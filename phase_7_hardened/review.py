"""The command: evidence first, lanes judge, code decides — hardened, and grouped by dependency direction.

    uv run python -m phase_7_hardened.review [repo] [--head B] [--base main | --all] [--path DIR]
        [--fail-on …] [--verify | --no-verify] [--max-tokens N] [--profile NAME | --check ID] [--dry-run] [--list-rules]

Phase 6's command, regrouped: `core/` is the domain and imports nothing that
runs a process or calls a model, `rules/` holds a project's own checks,
`config.toml` the profiles and the review policy, `collect/` gathers evidence, `judge/` is the
model boundary, `deliver/` is the report, and this file is the driver that
fixes the order of the steps. Each group may import only itself and the
groups before it; `tests/test_layering.py` keeps it that way. On top of the
regrouping, what advanced users ask for after a live run:

1. Retries on both arms (`judge/config.py`), set once on the request both clients read:
   `RETRY_ATTEMPTS` on Gemini, one on Copilot, whose SDK retries twice itself.
2. A token ceiling (`--max-tokens`) that ends the spending, never the report:
   the call that would pass it is refused, the lane is named, exit 3.
3. A second deterministic gate (`collect/gates.py`): ruff over the changed
   Python files at the head commit, findings under `gate_lint`.
4. A second opinion (`--verify`): another model judges each lane finding
   before the fold — one verifier per finding, a second graph run like the
   first; refuted findings are dropped and named, unjudged ones kept and
   named, the gates' findings never asked, nor a lane's that only says again
   what a gate found.
5. A blast radius (`core/blast.py`): what at the head depends on each changed
   file, read from the syntax tree, told to the lanes beside the diff and
   heading the report; the verdict never reads it.
6. Rules and profiles (`core/rules.py`, `rules/`): a project's own rules, one
   self-contained class a file — over each added line, each changed file, or
   the head — and named profiles of which checks run, chosen with
   `--profile`; `--list-rules` shows them all. Every definition is read from
   this folder; nothing is read from the repository under review.
7. What a review covers: `--path` keeps it to the change under a folder,
   the rest counted and named; `--all` reviews every file at the head, not
   what it changes. With neither a base nor `--all`, a person at a terminal
   is asked which; a pipeline gets the change against `main`, or `master`.

The order is still the architecture: deterministic evidence and gates first,
model judgement second, deterministic decision last; a model never decides
whether the build passes. `main` reads as that order.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
import tomllib
import warnings
from collections.abc import Collection, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath

from dotenv import load_dotenv
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import InMemoryRunner

from .collect.gates import LINT, lint_findings
from .collect.git import GitError, checked_out, collect_evidence, default_base, is_repository
from .core.findings import RANK, Finding, Review
from .core.rules import DEFAULT, RULES, AnyRule, chosen, expand, findings_of
from .core.secrets import GATE, gate_findings
from .core.verdict import (
    EXIT_CLEAN,
    EXIT_DEGRADED,
    EXIT_USAGE,
    Outcome,
    Sourced,
    decide,
    dedupe,
    drop_ungrounded,
    to_verify,
    where_quoted,
)
from .deliver.report import inert, one_line, render, render_checks, render_dry_run
from .judge.config import require_ready, serving
from .judge.graph import build_app
from .judge.lanes import LANE_NAMES, LANES, for_the_lanes, read_back, state_key
from .judge.plugins import RedactSecretsPlugin, UsageLedger
from .judge.run import Run, run_seeded
from .judge.verify import VERIFIER, judge_findings
from .rules import discover

ROOT = Path(__file__).resolve().parents[1]
#: The repository `scripts/make_demo_repo.py` builds, spelled as it spells it — a copy, because a phase folder
#: runs alone — so the command needs no path on stage.
DEMO_REPO = Path(tempfile.gettempdir()) / "adk-demo-repo"


def lane_check(name: str) -> str:
    """The id a profile turns one lane on with: the one place `lane.` is spelled."""
    return f"lane.{name}"


#: Each lane's check id and its state key, the source its findings carry.
LANE_CHECKS = {lane_check(name): state_key(name) for name in LANE_NAMES}
#: The checks built in, by the id a profile turns each on with, and the source their findings carry; the project's
#: own rules carry `RULES`. Beside the report's order, so a check added to one is seen missing from the other.
BUILT_IN = {"secrets": GATE, "lint": LINT, **LANE_CHECKS}
#: Report order, and the fold's on a tie: secrets, the project's own rules, lint, then the lanes in table order.
SOURCES = (GATE, RULES, LINT, *LANE_CHECKS.values())
#: Phase 7's one config file: the review policy, ruff's rule set and the profiles, beside this driver.
CONFIG = Path(__file__).with_name("config.toml")


def _codes(value: object) -> bool:
    """A list of ruff rule codes, none of them empty: what `[lint]`'s `rules` and `ignore` hold."""
    return type(value) is list and all(type(code) is str and code for code in value)


#: Every setting `config.toml` holds besides its profiles: the test its value must pass, and the sentence naming it.
#: `type`, never `isinstance`: TOML's `true` is a bool, and a bool is no number of tokens.
SETTINGS = {
    "review": {
        "fail_on": (lambda v: type(v) is str and v in RANK, "one of " + ", ".join(RANK)),
        "max_tokens": (lambda v: type(v) is int and v >= 0, "a whole number"),
        "verify": (lambda v: type(v) is bool, "true or false"),
    },
    "lint": {
        "rules": (lambda v: _codes(v) and bool(v), "a list of ruff rule codes"),
        "ignore": (_codes, "a list of ruff rule codes, empty for none"),
    },
}
#: What each section is a table of, as the sentence refusing another shape names it.
TABLES = {"review": "settings", "lint": "settings", "profiles": "named lists"}


def load_config(path: Path) -> dict:
    """`config.toml`, read whole: each section a table, each setting it must hold, as it must be, and nothing it
    does not know, since a key misspelt must never be a setting silently left at another value. What its profiles
    name is `chosen`'s to check. Anything else is a sentence, raised as `ValueError` for the command to answer
    with exit 2."""
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # as Windows Notepad has saved it: a BOM
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"config.toml: {exc}") from None
    if strangers := sorted(set(config) - set(TABLES)):
        raise ValueError(f"config.toml: no section [{strangers[0]}]; there are [review], [lint] and [profiles]")
    for section, of in TABLES.items():
        if type(config.setdefault(section, {})) is not dict:
            raise ValueError(f"config.toml: [{section}] must be a table of {of}")
    for section, settings in SETTINGS.items():
        given = config[section]
        if strangers := sorted(set(given) - set(settings)):
            raise ValueError(f"config.toml: [{section}] {strangers[0]} is not a setting")
        for key, (fits, what) in settings.items():
            if key not in given:
                raise ValueError(f"config.toml: [{section}] {key} is missing")
            if not fits(given[key]):
                raise ValueError(f"config.toml: [{section}] {key} must be {what}")
    return config


def build_parser(review: dict) -> argparse.ArgumentParser:
    """The command's flags, each setting's default taken from `config.toml`'s `[review]`: a flag wins for one run."""
    parser = argparse.ArgumentParser(
        prog="review", description="Review a branch: gates in Python, lanes judge, code decides."
    )
    parser.add_argument("repo", nargs="?", default=str(DEMO_REPO), help="path to the repository (default: the demo)")
    parser.add_argument("--head", help="the branch under review (default: the one checked out)")
    what = parser.add_mutually_exclusive_group()
    what.add_argument(
        "--base",
        help="the branch the change will be merged into; with neither this nor --all, a person at a terminal is "
        "asked, and anything else reviews the change against main, or master where there is no main",
    )
    what.add_argument("--all", action="store_true", help="review every file at the head, not what it changes")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        metavar="DIR",
        help="review only what lies under this folder of the repository; repeat it for more than one",
    )
    parser.add_argument(
        "--fail-on",
        choices=list(RANK),
        default=review["fail_on"],
        help=f"exit 1 at or above this severity (config.toml: {review['fail_on']}); what is below stays in the report",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=review["max_tokens"],
        help="stop spending past this many tokens, 0 for no ceiling (config.toml: "
        f"{review['max_tokens']}); what was found by then is still reported, refused lanes named",
    )
    parser.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=review["verify"],
        help="ask a second model whether each lane finding that says more than a gate holds, refuted ones named "
        f"(config.toml: {'on' if review['verify'] else 'off'})",
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--profile",
        default=DEFAULT,
        help=f"the checks to run, as config.toml's [profiles] names them; {DEFAULT}, every check, when not given",
    )
    which.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="ID",
        help="run only this check this once — a rule's id, secrets, lint, lane.<name>, or the groups rules and lanes; "
        "repeat it for more than one. How a rule's author tries a rule on a repository, with no profile edited",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve what would be reviewed — the revisions, the files, the profile, the model and whether it is "
        "ready — print it and stop: no gate, no rule, no model call",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="print every check — the gates, the lanes and the folder's rules — with its kind, its severity and the "
        "profiles that run it, then stop: no repository, no model, no key",
    )
    return parser


def checks_table(profiles: dict, rules: Sequence[AnyRule], known: Sequence[str], groups: dict) -> list[tuple]:
    """`--list-rules`: every check a profile may name, one row each — its id, its kind, the severity its findings
    carry, the profiles that run it, what it looks for and where it is defined."""
    runs = {profile: expand(ids, known, groups, f"profile {profile!r}") for profile, ids in profiles.items()}

    def where(check: str) -> str:
        return ", ".join([DEFAULT, *(profile for profile, ids in runs.items() if check in ids)])

    rows: list[tuple] = [
        (
            "secrets",
            "gate",
            "blocker",
            where("secrets"),
            "a credential-shaped value in an added line",
            "core/secrets.py",
        ),
        (
            "lint",
            "gate",
            "ruff's, by code",
            where("lint"),
            "ruff over the changed Python files at the head",
            "collect/gates.py",
        ),
        *(
            (lane_check(name), "lane", "the lane's, by finding", where(lane_check(name)), role, "judge/lanes.py")
            for name, role, _budget in LANES
        ),
    ]
    for rule in rules:
        module = type(rule).__module__.rsplit(".", 1)[-1]
        rows.append((rule.id, f"{rule.kind} rule", rule.severity, where(rule.id), rule.title, f"rules/{module}.py"))
    return rows


def scope_of(folders: Sequence[str]) -> tuple[str, ...]:
    """Each --path as git spells a folder: `/` between names, no `./`, no trailing `/`; `.` is the whole repository.
    One that starts at a root or a drive, or climbs out with `..`, is refused: git names nothing there."""
    scope = []
    for folder in folders:
        path = PurePosixPath(folder.replace("\\", "/"))
        if ".." in path.parts or PureWindowsPath(folder).anchor:  # a root or a drive, `/` or `\` alike
            raise ValueError(f"--path {folder!r} must name a folder inside the repository")
        if path.parts:
            scope.append(path.as_posix())
    return tuple(scope)


def target(repo: str, base: str | None, head: str | None, whole: bool) -> tuple[str | None, str]:
    """What to review, `(base, head)`, a base of None meaning every file at the head. With no --head, the branch
    checked out. With neither --base nor --all, a person at a terminal is asked; anything else, CI or a script, which
    nothing can ask, gets what the command always did: the change against `main`, or `master` where there is none.
    The terminal is both ends, the answer's stdin and the question's stderr: measured, with stderr sent to a file,
    the question went there and the command waited on a terminal that showed nothing."""
    if not is_repository(repo):
        return base, head or "HEAD"  # the collector names what is missing
    head = head or checked_out(repo)
    if head is None:
        raise ValueError(f"no branch is checked out in {repo}: name the one to review with --head")
    if base is not None or whole:
        return base, head
    default = default_base(repo)
    if sys.stdin.isatty() and sys.stderr.isatty():
        return _ask(head, default), head
    if default is None:
        raise ValueError(f"{repo} has no main or master branch: name the base with --base, or review it all with --all")
    return default, head


def _ask(head: str, default: str | None) -> str | None:
    """The one question the command asks, on stderr, so a report sent to a file is still only the report: the base
    to compare with, or None for the whole project. Asked again until answered; no answer is a usage error."""
    choices: dict[str, str | None] = {"1": default} if default else {}
    choices["2"] = None
    print(f"review: no --base given. What should be reviewed at {head!r}?", file=sys.stderr)
    if default:
        print(f"  1  what it changes against {default!r} (--base {default})", file=sys.stderr)
    print("  2  every file, the whole project (--all)", file=sys.stderr)
    while True:
        print(f"choose {' or '.join(choices)}: ", end="", file=sys.stderr, flush=True)
        try:
            answer = sys.stdin.readline()
        except KeyboardInterrupt:
            answer = ""
        if not answer:  # the end of the input, or Ctrl-C: no choice was made
            raise ValueError("no choice was made: name --base or --all")
        if answer.strip() in choices:
            return choices[answer.strip()]


def run_checks(
    evidence: dict, rules: Sequence[AnyRule], ran: Collection[str], select: Sequence[str], ignore: Sequence[str]
) -> tuple[list[Sourced], dict[str, str]]:
    """The gates and the project's own rules, by code, before any model: what each found, on the line or the path it
    names, and, as a lane that did not answer is, why one could not look. Measured by review: inline in `main`, this
    was rewritten each time a kind of check was added."""
    files = evidence["files"]
    gates = _sourced(GATE, gate_findings(files)) if GATE in ran else []
    ours, broken = findings_of(rules, files, evidence["tree"])
    gates += _sourced(RULES, ours)
    holes = {RULES: "; ".join(broken)} if broken else {}
    lint = lint_findings(evidence, select, ignore) if LINT in ran else []
    if isinstance(lint, str):
        holes[LINT] = lint
    else:
        gates += _sourced(LINT, lint)
    return gates, holes


def _sourced(source: str, findings: list[Finding]) -> list[Sourced]:
    """A check's findings under their source, each where the diff places it: its one line, or nowhere for one at a
    path, as a tree rule's is."""
    return [Sourced(source, f, None if f.line is None else (f.line, f.line)) for f in findings]


def not_read(files: list[dict], lanes: Collection[str]) -> dict[str, str]:
    """What no one could read, by path with why. A cut is the lanes' limit: with none on, the gates and the rules
    read every added line, and only what no one can read — binary, a submodule, nothing shown — is a hole."""
    return {f["path"]: f["unread"] for f in files if f["unread"] and (lanes or not f["cut"])}


def postprocess(run: Run, files: list[dict], lanes: tuple[str, ...], holes: dict[str, str]) -> Outcome:
    """The lanes' answers read back and grounded, each narrowing counted: what a model said that the diff bears out.
    `holes` are the checks that could not look before any model ran, named beside the lanes that could not.

    A lane that wrote nothing is named with why: the error event it ended
    with — its provider raised or timed out, the ceiling refused its call, the
    redaction plugin refused it — or, failing that, what escaped the engine,
    which names every lane that wrote nothing.
    """
    outcome = Outcome(unread=not_read(files, lanes), errors=dict(holes))
    quotable = {f["path"]: f["quotable"] for f in files}
    for key in map(state_key, lanes):  # a lane the profile left off did not fail: it was never asked
        review = read_back(run.state, key, Review, run.why(key, "the lane produced no output"))
        if isinstance(review, str):
            outcome.errors[key] = review
            continue
        kept, dropped = drop_ungrounded(review, quotable)
        outcome.kept += [Sourced(key, f, where_quoted(f, quotable)) for f in kept]
        outcome.dropped += [Sourced(key, f) for f in dropped]
    return outcome


def second_opinion(outcome: Outcome, gates: list[Sourced], diff: str, plugins: list[BasePlugin]) -> None:
    """`--verify`: each lane finding that says more than a gate judged once more — refuted ones out and named,
    unjudged ones kept and named.

    Before the fold, so the gates' findings — facts — are never asked about, and
    a gate's reading of a line stands whatever the verifier says of a lane's.
    Nor is a lane's finding that only says again what a gate found: the fold
    folds it into the gate's, as without `--verify`, so a verifier that holds
    everything leaves the report it would have been. Measured live on Copilot,
    2 of 5 verifier calls judged a lane's reading of a key the secrets gate had found.
    """
    outcome.verified = True
    asked = to_verify(outcome.kept, gates)
    judged = asyncio.run(judge_findings([item.finding for item in asked], diff, plugins))
    refuted: set[int] = set()  # by identity: two lanes can file the same finding
    for item, judgement in zip(asked, judged, strict=True):
        if isinstance(judgement, str):
            outcome.unverified.append((item, judgement))
        elif not judgement.holds:
            outcome.refuted.append((item, judgement.reason))
            refuted.add(id(item))
    outcome.kept = [item for item in outcome.kept if id(item) not in refuted]


def fold(outcome: Outcome, gates: list[Sourced]) -> None:
    """One finding per span of the diff, the first source on a tie: `SOURCES`'s order, by construction, so the fold
    and the report never disagree on which check a line belongs to."""
    kept = sorted(gates + outcome.kept, key=lambda item: SOURCES.index(item.source))  # stable: each source's own order
    outcome.kept, outcome.folded = dedupe(kept)


def _say(sentence: str) -> None:
    """A sentence on stderr, made safe as the report's prose is: git's or an exception's words can be the branch's."""
    print(f"review: {inert(one_line(sentence))}", file=sys.stderr)


def _review(argv: list[str] | None = None) -> int:
    try:
        load_dotenv(ROOT / ".env")
    except UnicodeDecodeError:
        _say("the central .env is not UTF-8; save it as UTF-8 (Windows PowerShell 5.1's `>` writes UTF-16)")
        return EXIT_USAGE
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    try:  # before anything runs: the config, the rules and the profiles read whole, or a sentence and exit 2
        config = load_config(CONFIG)
        args = build_parser(config["review"]).parse_args(argv)
        rules = discover()
        known = (*BUILT_IN, *(rule.id for rule in rules))
        # The two groups a profile may name instead of ids: every rule in the folder, every lane.
        groups = {
            "rules": [rule.id for rule in rules],
            "lanes": list(LANE_CHECKS),
        }
        profile, on = chosen(config["profiles"], args.profile, known, groups)
        if args.check:  # one run's own list, held to what a profile is, and named in the report as the flag
            profile, on = "--check " + " ".join(args.check), expand(args.check, known, groups, "--check")
        scope = scope_of(args.path)
    except ValueError as exc:
        _say(str(exc))
        return EXIT_USAGE
    if args.list_rules:
        print(render_checks(checks_table(config["profiles"], rules, known, groups)))
        return EXIT_CLEAN
    ran = {BUILT_IN.get(check, RULES) for check in on}  # the source each check that runs files its findings under
    lanes = tuple(name for name in LANE_NAMES if lane_check(name) in on)
    # Only a lane calls a model: a profile without one needs no key, and the verifier has no lane finding to judge.
    verify = args.verify and bool(lanes)
    why = require_ready(roles=(VERIFIER,) if verify else ()) if lanes else None
    if why is not None and not args.dry_run:  # a dry run reports an arm that is not ready; a review stops at it
        _say(why)
        return EXIT_USAGE
    try:
        base, head = target(args.repo, args.base, args.head, args.all)
    except (ValueError, GitError) as exc:
        _say(str(exc))
        return EXIT_USAGE
    evidence = collect_evidence(args.repo, base, head, scope)
    if evidence["status"] != "success":
        _say(evidence["error_message"])
        return EXIT_USAGE
    files = evidence["files"]
    off = [check for check in known if check not in on]
    if args.dry_run:
        print(
            render_dry_run(
                evidence,
                model=serving() if lanes else "",
                profile=profile,
                on=on,
                off=off,
                lanes=lanes,
                ready=why or "ready",
                unread=not_read(files, lanes),
            )
        )
        return EXIT_CLEAN
    lint = config["lint"]
    gates, holes = run_checks(evidence, [rule for rule in rules if rule.id in on], ran, lint["rules"], lint["ignore"])
    del evidence["tree"]  # read by the gates; not held through the model calls
    for entry in files:  # nor the changed files' texts, read by the file rules
        entry["text"] = None

    app = build_app(chat=False, ceiling=args.max_tokens or None, lanes=lanes)  # 0 is no ceiling
    redactor = next(p for p in app.plugins if isinstance(p, RedactSecretsPlugin))
    ledger = next(p for p in app.plugins if isinstance(p, UsageLedger))
    seeded = {"diff": evidence["diff"], "blast": for_the_lanes(evidence["blast"])}
    # The lanes-only graph over a session seeded with the diff and the blast radius beside it; every lane finishes,
    # whatever one of them does.
    run = asyncio.run(run_seeded(InMemoryRunner(app=app), session_id="run", state=seeded, prompt="review"))

    outcome = postprocess(run, files, lanes, holes)
    if verify:
        second_opinion(outcome, gates, evidence["diff"], app.plugins)
    outcome.redacted = redactor.redacted  # read after the verifiers, whose calls the same plugin scrubs
    fold(outcome, gates)
    verdict, code = decide(outcome, args.fail_on)
    print(
        render(
            evidence,
            outcome,
            verdict=verdict,
            spend=ledger.render(),
            fail_on=args.fail_on,
            model=serving() if lanes else "",  # no lane, no model to name
            profile=profile,
            off=off,
            sources=[source for source in SOURCES if source in ran],
        )
    )
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
