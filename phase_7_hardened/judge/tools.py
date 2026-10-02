"""The model-facing tools, and the guardrail in front of them.

ADK builds a tool's schema from the function signature and its docstring, so
the docstring is prompt material: it tells the model when to call the tool and
what comes back. Every tool returns a `{"status": ...}` dict and never raises
at the model. A parameter named `tool_context` is filled in by ADK, never by
the model: it is how a tool reaches session state — where `inspect_repository`
leaves the scope it confirmed, so the tools after it take no repository at
all. The model chooses tool arguments, so a tool argument is untrusted input:
`only_changed_paths` runs before every call. The git itself is in
`collect/git.py`; this module only speaks to the model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ..collect.git import GitError, capped, diff_of, list_changed, preflight, radius_of, tree_at_head
from .lanes import for_the_lanes


def inspect_repository(repo: str, base: str, head: str, tool_context: ToolContext) -> dict:
    """Confirm `repo` is a git repository, that `base` and `head` exist, and find their merge base.

    Call this before anything else: the tools after it read the repository
    and branches it confirmed from session state and never ask for them
    again. Both branches must exist; a missing one is an error to report,
    never something to guess.

    Args:
        repo: Absolute path to the repository's root directory.
        base: The branch the change will be merged into, usually "main".
        head: The branch under review.

    Returns:
        On success: {"status": "success", "repo", "base", "base_sha", "head", "head_sha",
        "merge_base", "commits_ahead", "base_ref", "head_ref"}. On failure: {"status": "error", "error_message": "..."}.
    """
    resolved = preflight(repo, base, head)
    # A failed preflight clears the scope: nothing later may read a repository this call did not confirm.
    tool_context.state["review_scope"] = resolved if resolved["status"] == "success" else None
    tool_context.state["review_files"] = None
    tool_context.state["blast"] = None  # and a new scope never carries the last one's blast radius
    return resolved


def changed_files(tool_context: ToolContext) -> dict:
    """List the files the branch under review changed, with a status letter each.

    Call this after inspect_repository and before show_diff: it reads the
    scope inspect_repository confirmed, and the paths it returns are the only
    paths show_diff will accept.

    Returns:
        On success: {"status": "success", "files": [{"path": ..., "status": "A|M|D|R", "old": ... for R}],
        "count": int}.
        On failure: {"status": "error", "error_message": "..."}.
    """
    scope = tool_context.state.get("review_scope")
    if not scope:
        return {"status": "error", "error_message": "call inspect_repository first; changed_files lists its change"}
    try:
        files = list_changed(scope)
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    # The allowlist show_diff reads, each path with the old one a rename carries, so its diff reads both.
    tool_context.state["review_files"] = {f["path"]: f.get("old", "") for f in files}
    # The reviewers read the blast radius from state, as the command seeds it; the intake is never asked to copy it.
    # Once per scope, which inspect_repository resets: it cannot change within one, and LiteLLM's tree takes 4.6 s.
    if tool_context.state.get("blast") is None:
        tool_context.state["blast"] = for_the_lanes(radius_of(tree_at_head(scope), files))
    return {"status": "success", "files": files, "count": len(files)}


def show_diff(path: str, tool_context: ToolContext) -> dict:
    """The unified diff of one changed file, capped at 4,000 characters.

    Only a path that changed_files returned is accepted. A long diff is cut
    and the cut is marked in the text, so what you see is all you can cite.

    Args:
        path: A repository-relative path from changed_files.

    Returns:
        On success: {"status": "success", "path": ..., "diff": ..., "cut": bool}.
        On failure: {"status": "error", "error_message": "..."}.
    """
    scope = tool_context.state.get("review_scope")
    if not scope:
        return {"status": "error", "error_message": "call inspect_repository first; show_diff reads what it confirmed"}
    old = (tool_context.state.get("review_files") or {}).get(path, "")  # a rename is read with its old path
    try:
        diff, cut = capped(diff_of(scope, path, old))  # the line breaks the command's lanes read
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    return {"status": "success", "path": path, "diff": diff, "cut": cut}


def only_changed_paths(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> dict | None:
    """The guardrail: refuse a repository that is not a directory (inspect_repository is the one tool that takes
    one), and a diff path the change did not touch."""
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
