"""The same review as a command.

    uv run python -m phase_4_first_review.review <repo> --base main --head feature/payments

The graph `adk web` runs, driven by code: the arguments become the message the
chat needed, ADK's in-memory runner takes the web UI's place, the typed `Review`
the reviewer left in state is printed as JSON, and the exit code says how the
run went. 0: the reviewer judged the diff. 2: a usage error — a provider
`config.py` does not know, a path or a branch that does not exist — caught before
a model call is spent, the branches by the collector's own preflight, run by
code. 3: an agent could not reach its provider; it said so in its
own error event, the reviewer judged nothing and said why, and a run that did
not look never exits 0. What the findings mean for a build is phase 6's lesson:
there, code decides against a bar. The root `.env` is loaded here, before the
agents are built — `build_model()` reads the provider when `agent.py` is
imported, which is why the package's `__init__` imports nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import warnings
from pathlib import Path

from dotenv import load_dotenv
from google.adk.apps.app import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from .config import build_model
from .tools import _preflight

ROOT = Path(__file__).resolve().parents[1]
#: The repository `scripts/make_demo_repo.py` builds, spelled the way it spells it — a copy, because a phase folder
#: runs alone — so the command needs no path on stage.
DEMO_REPO = Path(tempfile.gettempdir()) / "adk-demo-repo"
EXIT_CLEAN, EXIT_USAGE, EXIT_DEGRADED = 0, 2, 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review",
        description="Review a branch: the collector gathers, the reviewer judges.",
    )
    parser.add_argument("repo", nargs="?", default=str(DEMO_REPO), help="path to the repository (default: the demo)")
    parser.add_argument("--base", default="main", help="the branch the change will be merged into")
    parser.add_argument("--head", required=True, help="the branch under review")
    return parser


async def run(root_agent, message: str) -> tuple[dict, list[str]]:
    """One turn through ADK's in-memory runner: the session state after it, and every agent that failed, by name."""
    app = App(name=root_agent.name, root_agent=root_agent)
    runner = InMemoryRunner(app=app)
    await runner.session_service.create_session(app_name=app.name, user_id="cli", session_id="cli")
    failed: list[str] = []
    async for event in runner.run_async(user_id="cli", session_id="cli", new_message=types.UserContent(message)):
        if event.error_code:  # the hook's answer for an agent that could not reach its provider
            failed.append(f"{event.author}: {event.error_code}: {event.error_message}")
    session = await runner.session_service.get_session(app_name=app.name, user_id="cli", session_id="cli")
    return dict(session.state), failed


def _review(argv: list[str] | None = None) -> int:
    try:
        load_dotenv(ROOT / ".env")
    except UnicodeDecodeError:
        print(
            "review: the central .env is not UTF-8; save it as UTF-8 (Windows PowerShell 5.1's `>` writes UTF-16)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    args = build_parser().parse_args(argv)
    try:
        build_model()  # the provider `.env` names, checked before anything is spent
    except ValueError as exc:
        print(f"review: {exc}", file=sys.stderr)
        return EXIT_USAGE
    repo = str(Path(args.repo).resolve())
    preflight = _preflight(repo, args.base, args.head)  # the collector's own check, by code, before a model call
    if preflight["status"] != "success":
        print(f"review: {preflight['error_message']}", file=sys.stderr)
        return EXIT_USAGE
    from .agent import root_agent  # after `.env`: importing the module builds the agents

    state, failed = asyncio.run(run(root_agent, f"review {repo}, branch {args.head} against {args.base}"))
    for why in failed:
        print(f"review: {why}", file=sys.stderr)
    if (review := state.get("review")) is None:
        print("review: the reviewer answered nothing", file=sys.stderr)
        return EXIT_DEGRADED
    print(json.dumps(review, indent=2, ensure_ascii=False))
    return EXIT_DEGRADED if failed else EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    """The command, with a last resort: an error nothing above named ends as one sentence and exit 3, a review that
    did not finish, never Python's own exit 1, which is the code for "a blocker was found". Measured before: errors
    found and named one at a time, six recorded in the design record and a seventh by review, each ended so."""
    try:
        return _review(argv)
    except Exception as exc:  # noqa: BLE001 -- a crash must never read as a verdict
        print(f"review: the review did not finish: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_DEGRADED


if __name__ == "__main__":
    # Process-wide settings belong at the process boundary, once; `main` stays a function of its arguments.
    warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")  # ADK announces a flag on every tool declaration
    # ADK logs a failed node with its whole traceback through Python's last-resort stderr handler; the command names
    # the agent and the reason, so that logger gets a handler that prints nothing. genai warns on every Gemini call
    # that it would rather be called another way: the same handler. Configured logging still receives every record.
    for name in ("google_adk", "google_genai"):
        logging.getLogger(name).addHandler(logging.NullHandler())
    raise SystemExit(main())
