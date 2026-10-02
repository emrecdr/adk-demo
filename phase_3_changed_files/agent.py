"""Phase 3 — changed files.

The agent lists what the branch changed and shows a capped diff of any one
changed file. New: two tools, and a `before_tool_callback` that treats the
model's arguments as hostile input — a diff path must be one the change
touched. `changed_files` writes that allowlist into session state, so one
tool's answer becomes the next tool's boundary.
"""

from __future__ import annotations

from google.adk.agents import Agent

from .callbacks import only_changed_paths
from .config import build_model
from .tools import changed_files, inspect_repository, show_diff

root_agent = Agent(
    model=build_model(),
    name="phase_3_changed_files",
    description="Lists what a branch changed and shows the diff of any one changed file.",
    instruction=(
        "You prepare a code review. You need the absolute path of a git repository, the base branch "
        "(assume 'main' if the person does not say), and the branch under review; ask for anything "
        "missing, never invent it.\n\n"
        "Steps: call inspect_repository first. Then call changed_files and reply with the preflight "
        "lines (repository, branch @ sha, against @ sha, merge-base, ahead) followed by one line per "
        "changed file: `<status>  <path>`. Only when the person asks for a particular file, call "
        "show_diff for it and reply with the diff in a fenced block. If a tool answers with an error, "
        "repeat its message in one sentence and stop."
    ),
    tools=[inspect_repository, changed_files, show_diff],
    before_tool_callback=[only_changed_paths],
    output_key="preflight",
)
