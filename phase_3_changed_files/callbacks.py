"""A guardrail in front of the tools.

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

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext


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
