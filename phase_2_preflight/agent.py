"""Phase 2 — preflight.

The agent asks for a repository and two branches, proves they exist with one
function tool, and prints a preflight block before anything else
happens. Everything new is in `tools.py`; the agent only gained a
`tools=` list and an instruction that says when to call it and how to answer.
"""

from __future__ import annotations

from google.adk.agents import Agent

from .config import build_model
from .tools import inspect_repository

root_agent = Agent(
    model=build_model(),
    name="phase_2_preflight",
    description="Checks that a repository and two branches exist before a review starts.",
    instruction=(
        "You prepare a code review. You need three things: the absolute path of a git repository, "
        "the base branch (assume 'main' if the person does not say), and the branch under review. "
        "If the path or the branch under review is missing, ask for it; do not invent either.\n\n"
        "Once you have them, call inspect_repository. On success, reply with exactly these lines "
        "and nothing else, using the first nine characters of each commit hash:\n"
        "  repository   <repo>\n"
        "  branch       <head> @ <head_sha>\n"
        "  against      <base> @ <base_sha>\n"
        "  merge-base   <merge_base>\n"
        "  ahead        <commits_ahead> commit(s)\n"
        "On an error, repeat the tool's error message in one sentence and ask what to change."
    ),
    tools=[inspect_repository],
    output_key="preflight",
)
