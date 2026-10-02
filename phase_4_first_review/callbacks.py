"""A guardrail in front of the tools, and the guard that skips a reviewer with nothing to judge.

The model chooses tool arguments, so a tool argument is untrusted input: a
review agent that can be talked into `show_diff("/etc/passwd")` is a file
reader with a chat interface. `before_tool_callback` runs before every tool
call; returning a dict answers the model without running the tool, returning
None lets the call through. The allowlist is whatever `changed_files` last put
in session state — one tool's answer is the next tool's boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .schemas import Review


def only_changed_paths(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """Refuse a repository that is not a directory (inspect_repository is the one tool that takes one), and a
    diff path the change did not touch."""
    repo = args.get("repo")
    if repo is not None and not Path(os.path.expanduser(str(repo))).is_dir():
        return {"status": "error", "error_message": f"{repo} is not a directory; ask for the repository path"}
    if tool.name != "show_diff":
        return None
    path = str(args.get("path", ""))
    listed = tool_context.state.get("review_files")
    if listed is None:
        return {"status": "error", "error_message": "call changed_files first; show_diff only accepts a path it listed"}
    if Path(path).is_absolute() or ".." in Path(path).parts or path not in listed:
        return {
            "status": "error",
            "error_message": f"{path!r} is not one of the files this change touched; choose one changed_files listed",
        }
    return None


def without_evidence(callback_context: CallbackContext) -> types.Content | None:
    """A reviewer judges evidence and does not run without it: skipped, answering its schema, when there is none.

    When the collector's provider failed, its answer was a sentence and
    `temp:failure` is in state for this invocation; a reviewer run over that
    sentence would review an apology and find nothing, and "did not look"
    must never read as "found nothing". Returning content from
    `before_agent_callback` skips the agent, and ADK saves that content under
    its `output_key` through its schema — so the answer is a `Review` with no
    findings and a summary that says why.
    """
    failure = callback_context.state.get("temp:failure")
    if not failure and callback_context.state.get("diff"):
        return None
    summary = "Nothing was gathered, so nothing was judged" + (f": {failure}" if failure else ".")
    return types.ModelContent(Review(summary=summary).model_dump_json())
