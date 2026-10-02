"""Every phase's demo line, in order, paced: `uv run python scripts/rehearse.py [--pause SECONDS] [--dry-run]`.

The evening before the talk: the same commands the READMEs show, one after
another, ending with the fix-and-rerun moment (which leaves the demo
repository fixed until the next run rebuilds it), each as its own process
so a failure is one step's exit code, a step past `STEP_TIMEOUT_S` is
stopped, and the next step still runs; a summary at the end says which passed. `--pause`
waits between steps — measured on Gemini's free tier, five requests a minute
per model is the whole budget, and one step can pass it alone: phase 7's
`--verify` made ten there, and five and seven in two Copilot runs since a
lane's restatement of a gate went unasked — and `--dry-run` prints the
commands instead of running them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_REPO = Path(tempfile.gettempdir()) / "adk-demo-repo"
REVIEW = f"review {DEMO_REPO}, branch feature/payments against main"
#: With its base named: with neither `--base` nor `--all`, phase 7 asks at a terminal, and the rehearsal runs at one.
COMMAND = ["-m", "phase_7_hardened.review", "--head", "feature/payments", "--base", "main"]
#: The exit codes a step answers when it went as the talk means it to: 0 where no step gives a verdict (phase 4
#: never exits 1), so an uncaught exception, Python's exit 1, is seen there; 0 or 1, a verdict, from phase 5 on; and 3
#: for the ceiling, whose lesson is the ceiling refusing. Measured before: that 3 failed every clean rehearsal.
CLEAN, VERDICT, CEILING = {0}, {0, 1}, {3}
#: (label, argv after the interpreter, the exit codes it answers), in the order the talk runs them.
STEPS = (
    ("make the demo repository", ["scripts/make_demo_repo.py"], CLEAN),
    ("phase 1: hello", ["scripts/ask.py", "phase_1_hello_world", "hello"], CLEAN),
    ("phase 2: preflight", ["scripts/ask.py", "phase_2_preflight", REVIEW], CLEAN),
    ("phase 3: changed files", ["scripts/ask.py", "phase_3_changed_files", REVIEW], CLEAN),
    ("phase 4: the first review", ["-m", "phase_4_first_review.review", "--head", "feature/payments"], CLEAN),
    ("phase 5: parallel lanes", ["-m", "phase_5_parallel_lanes.review", "--head", "feature/payments"], VERDICT),
    ("phase 6: the command", ["-m", "phase_6_reviewer.review", "--head", "feature/payments"], VERDICT),
    ("phase 7: gate_lint joins", COMMAND, VERDICT),
    ("phase 7: --verify", [*COMMAND, "--verify"], VERDICT),
    ("phase 7: --max-tokens 2000", [*COMMAND, "--max-tokens", "2000"], CEILING),
    ("phase 7: --profile gates-only", [*COMMAND, "--profile", "gates-only"], VERDICT),
    # The talk's fix-and-rerun moment, last, since it leaves the demo repository fixed; the next run rebuilds it.
    ("the fix: make_demo_repo.py --fix", ["scripts/make_demo_repo.py", "--fix"], CLEAN),
    ("phase 6 after the fix", ["-m", "phase_6_reviewer.review", "--head", "feature/payments"], CLEAN),
)
#: Past this, a step is stopped and named, and the next still runs: phases 4 and 5 set no request deadline, and
#: measured by review, one hung call stalled the whole rehearsal.
STEP_TIMEOUT_S = 600


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rehearse", description="Run every phase's demo line, paced.")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between steps (a quota's worth)")
    parser.add_argument("--dry-run", action="store_true", help="print the commands and run nothing")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    results: list[tuple[str, int | None, set[int]]] = []
    for number, (label, tail, expected) in enumerate(STEPS):
        argv_ = [sys.executable, *tail]
        print(f"\n=== {label}\n$ {' '.join(argv_)}", flush=True)
        if args.dry_run:
            continue
        if number and args.pause:
            time.sleep(args.pause)
        try:
            code = subprocess.run(argv_, cwd=ROOT, encoding="utf-8", check=False, timeout=STEP_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            code = None  # stopped: never what a step answers
        results.append((label, code, expected))
    if args.dry_run:
        return 0
    print("\n=== rehearsal")
    for label, code, expected in results:
        said = f"timed out after {STEP_TIMEOUT_S} s" if code is None else f"exit {code}"
        print(f"- {said}  {label}" + ("" if code in expected else "  <- not what the talk expects"))
    return 0 if all(code in expected for _label, code, expected in results) else 3


if __name__ == "__main__":
    raise SystemExit(main())
