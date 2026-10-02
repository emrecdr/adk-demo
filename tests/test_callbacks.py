"""The guardrail: a tool argument the model chose is hostile input until it is checked — in every phase that carries
it. Measured before: only phase 3's copy ran under a test; phases 4 to 7 carried theirs untested."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from conftest import UNKNOWN_USER_REPO, tool_context

#: Where each phase keeps its guardrail.
GUARDS = {
    "phase_3_changed_files": "phase_3_changed_files.callbacks",
    "phase_4_first_review": "phase_4_first_review.callbacks",
    "phase_5_parallel_lanes": "phase_5_parallel_lanes.callbacks",
    "phase_6_reviewer": "phase_6_reviewer.tools",
    "phase_7_hardened": "phase_7_hardened.judge.tools",
}
pytestmark = pytest.mark.parametrize("phase", sorted(GUARDS))


def _call(phase: str, tool_name: str, args: dict, listed: list[str] | None = None) -> dict | None:
    context = tool_context(review_files=listed) if listed is not None else tool_context()
    only_changed_paths = importlib.import_module(GUARDS[phase]).only_changed_paths
    return only_changed_paths(SimpleNamespace(name=tool_name), args, context)


def test_a_listed_path_is_allowed_through(phase: str) -> None:
    assert _call(phase, "show_diff", {"path": "src/a.py"}, listed=["src/a.py"]) is None


def test_a_path_the_model_invented_is_refused_before_the_tool_runs(phase: str) -> None:
    refused = _call(phase, "show_diff", {"path": "/etc/passwd"}, listed=["src/a.py"])
    assert refused and refused["status"] == "error" and "changed_files" in refused["error_message"]


def test_a_traversal_is_refused_even_if_it_were_listed(phase: str) -> None:
    refused = _call(phase, "show_diff", {"path": "../secrets"}, listed=["../secrets"])
    assert refused and refused["status"] == "error"


def test_without_a_list_yet_the_model_is_told_to_ask_for_one(phase: str) -> None:
    refused = _call(phase, "show_diff", {"path": "src/a.py"})
    assert refused and "changed_files first" in refused["error_message"]


def test_a_repository_argument_must_be_a_directory(phase: str) -> None:
    refused = _call(phase, "inspect_repository", {"repo": "/definitely/not/here", "base": "main", "head": "x"})
    assert refused and "not a directory" in refused["error_message"]


def test_a_repository_argument_naming_an_unknown_user_is_refused_not_raised(phase: str) -> None:
    """An unknown `~name` stays as typed and is no directory; `Path.expanduser` raised here once."""
    refused = _call(phase, "inspect_repository", {"repo": UNKNOWN_USER_REPO, "base": "main", "head": "x"})
    assert refused and "not a directory" in refused["error_message"]
