"""How often the lanes find what the demo plants: `uv run python scripts/measure.py [--runs N] [--phase 6|7]
[--pause S] [--all]`.

What code finds is found every run; a lane's findings are the model's doing and vary. This builds the planted
branch, reviews it N times, and reads each report as a person would: per planted defect, in how many runs a lane
named it, kept or folded into another source's finding; the exit code the planted blockers call for, 1, and in how
many runs it came; the findings dropped for a quote the diff does not bear out; the tokens and the time. Each run
calls the model: on Copilot, the talk's arm, about 5,000 tokens. The report names the reviewer's commit it measured.
`--all` reviews the planted branch as a whole project, every file at its head, as phase 7's `--all` does: a file's
line there is its line at the head, as on the diff's new side, so the planted lines are read the same way.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {6: "phase_6_reviewer.review", 7: "phase_7_hardened.review"}
#: Each planted defect: its file and its lines, as `make_demo_repo.py` plants them.
PLANTED = {
    "shell call": ("src/payments/charge.py", range(22, 29)),
    "key pair": ("src/payments/config.py", range(4, 6)),
    "untested function": ("src/payments/refund.py", range(1, 12)),
    "copied block": ("src/payments/report.py", range(4, 6)),  # its lines hold the cents division too: either counts
}
#: A finding in a report, kept (`- **major** …`) or folded into another's, ending in its `(path:line)`.
FINDING = re.compile(
    r"^- (?:\*\*\w+\*\* |folded into `\w+`'s finding on the same lines: ).*\((?P<path>[^():]+):(?P<line>\d+)\)$"
)
SPEND = re.compile(r"^- spend: \d+ model call\(s\) completed of \d+ attempted, (?P<tokens>[\d,]+) tokens")
DROPPED = "- findings dropped for evidence not in the diff: "


def read(report: str) -> tuple[set[str], int, int]:
    """What a person reads off one report: the planted defects a lane named, kept or folded; how many findings
    were dropped for a quote the diff does not bear out; and the tokens spent."""
    source, found, dropped, tokens = "", set(), 0, 0
    for line in report.splitlines():
        if line.startswith("### "):
            source = line[4:].split(" ")[0]
        elif (hit := FINDING.match(line)) and source.startswith("lane_"):
            at = (hit["path"], int(hit["line"]))
            found |= {name for name, (path, lines) in PLANTED.items() if at[0] == path and at[1] in lines}
        elif line.startswith(DROPPED):
            dropped = int(line.removeprefix(DROPPED))
        elif spent := SPEND.match(line):
            tokens = int(spent["tokens"].replace(",", ""))
    return found, dropped, tokens


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    parser = argparse.ArgumentParser(prog="measure", description="How often the lanes find what the demo plants.")
    parser.add_argument("--runs", type=int, default=3, help="reviews of the planted branch (each calls the model)")
    parser.add_argument("--phase", type=int, choices=sorted(COMMANDS), default=7, help="the command to measure")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between runs (a quota's worth)")
    parser.add_argument("--all", action="store_true", help="review every file at the head, not the change (phase 7)")
    args = parser.parse_args(argv)
    if args.all and args.phase != 7:
        parser.error("--all is phase 7's: phase 6 reviews a change")
    subprocess.run([sys.executable, "scripts/make_demo_repo.py"], cwd=ROOT, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, encoding="utf-8"
    )
    command = [sys.executable, "-m", COMMANDS[args.phase], "--head", "feature/payments"]
    if args.all:
        command.append("--all")
    runs: list[tuple[int | None, float, set[str], int, int]] = []
    for number in range(args.runs):
        if number and args.pause:
            time.sleep(args.pause)
        started = time.monotonic()
        try:
            done = subprocess.run(
                command, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=600
            )
            code, report = done.returncode, done.stdout
        except subprocess.TimeoutExpired:
            code, report = None, ""
        runs.append((code, time.monotonic() - started, *read(report)))
        found = ", ".join(sorted(runs[-1][2])) or "none of the planted defects"
        print(f"run {number + 1}: exit {code}, a lane named {found}", flush=True)
    total = len(runs)
    what = "the planted branch as a whole project" if args.all else "the planted branch"
    print(f"\nphase {args.phase} at {head.stdout.strip() or 'an unknown commit'}, {total} runs of {what}")
    for name in PLANTED:
        print(f"- {name}: named by a lane in {sum(name in found for _c, _s, found, _d, _t in runs)} of {total}")
    print(f"- exit 1, the verdict the planted blockers call for: {sum(code == 1 for code, *_ in runs)} of {total}")
    print(f"- findings dropped for a quote the diff does not bear out: {sum(run[3] for run in runs)} in all")
    tokens, seconds = sum(run[4] for run in runs) // max(total, 1), sum(run[1] for run in runs) / max(total, 1)
    print(f"- a run: {tokens:,} tokens, {seconds:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
