"""One headless turn through any phase: `uv run python scripts/ask.py phase_2_preflight '...'`.

The embedded-Runner shape the commands from phase 4 on build on, kept at the root
so any phase can be exercised without the web UI: import the phase, take its `app` when it
exports one (that is how plugins travel) or wrap `root_agent` in a bare `App`,
open a session, send one message, print the final text and what it cost. An
agent that failed ended as its own error event — the hook's answer, or the
runner's own before it re-raises — and it is printed by name; what still
escapes the engine — a provider error no hook caught, a misspelled `.env`, a
placeholder the state lacks, the engine itself — is one line and exit 3,
never a traceback, because the last line of one is all a reader wants.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
from google.adk.apps.app import App
from google.adk.runners import InMemoryRunner
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]


def _quiet_litellm() -> None:
    """LiteLLM prints a red "Give Feedback" banner on stdout with every error it maps. It serves the Copilot arm
    alone, and is imported only there: at the top of this script it cost about a second of every turn, and on its
    own import it read `.env` unless told it runs in production, as ADK tells it, and fetched a price list unless
    `LITELLM_LOCAL_MODEL_COST_MAP` is set. Every phase goes through here, the three before the review commands
    among them, which turn nothing off themselves."""
    if os.environ.get("REVIEW_PROVIDER", "").strip().lower() in ("", "copilot"):  # blank is the default arm
        os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
        import litellm

        litellm.suppress_debug_info = True


async def ask(phase: str, message: str) -> str:
    module = importlib.import_module(f"{phase}.agent")
    app = getattr(module, "app", None) or App(name=phase, root_agent=module.root_agent)
    runner = InMemoryRunner(app=app)  # ADK's own in-memory session, artifact and memory services, in one line
    await runner.session_service.create_session(app_name=app.name, user_id="demo", session_id="demo")
    final, tokens_in, tokens_out = "(no response)", 0, 0
    async for event in runner.run_async(user_id="demo", session_id="demo", new_message=types.UserContent(message)):
        if event.usage_metadata:
            tokens_in += event.usage_metadata.prompt_token_count or 0
            tokens_out += event.usage_metadata.candidates_token_count or 0
        if event.error_code:  # a failed agent's own error event, by name
            print(f"[error] {event.author}: {event.error_code}: {_short(event.error_message or '')}", file=sys.stderr)
        if event.is_final_response() and event.content and event.content.parts:
            final = event.content.parts[0].text or final
    # A phase that carries a ledger says what each agent cost; the others get the runner's own count.
    rendered = [plugin.render() for plugin in app.plugins if hasattr(plugin, "render")]
    print("\n".join(rendered) if rendered else f"[tokens] in={tokens_in} out={tokens_out}", file=sys.stderr)
    return final


def _short(text: str) -> str:
    """One line of readable length for what no hook described: an escaped exception, or an event carrying raw text."""
    text = " ".join(text.split())
    return text if len(text) <= 400 else f"{text[:400]} [… cut at 400 characters]"


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # a Windows console is not UTF-8 by default
    if len(argv) < 2:
        print("usage: ask.py <phase_folder> <message>", file=sys.stderr)
        return 2
    try:
        load_dotenv(ROOT / ".env")
    except UnicodeDecodeError:
        print(
            "ask: the central .env is not UTF-8; save it as UTF-8 (Windows PowerShell 5.1's `>` writes UTF-16)",
            file=sys.stderr,
        )
        return 2
    warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")  # ADK announces a flag on every tool declaration
    # As the phase 6 and 7 drivers do: ADK's failed-node traceback and genai's calling-convention warning are noise
    # on stage, and configured logging still receives every record.
    for name in ("google_adk", "google_genai"):
        logging.getLogger(name).addHandler(logging.NullHandler())
    _quiet_litellm()
    sys.path.insert(0, str(ROOT))
    try:
        print(asyncio.run(ask(argv[0], " ".join(argv[1:]))))
    except Exception as exc:  # noqa: BLE001 -- what escaped the engine, named
        print(f"ask: {type(exc).__name__}: {_short(str(exc))}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
