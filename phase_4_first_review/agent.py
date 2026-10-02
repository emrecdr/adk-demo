"""Phase 4 — the first review.

Two agents and one sequential edge. ADK 2.9.2 allows `tools=` and
`output_schema=` on one agent, through an extra tool, but they stay apart here:
gathering and judging are different jobs with different prompts. The collector has the tools and puts
the diffs in state under `diff`; the reviewer has the schema, reads `{diff}`
from its instruction, and puts a typed `Review` in state under `review`.
`Workflow` with a tuple of two agents is a sequence; the same class fans out
in phase 5.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.workflow import Workflow

from .callbacks import only_changed_paths, without_evidence
from .config import build_model, request_config, when_the_model_fails
from .schemas import Review
from .tools import changed_files, inspect_repository, show_diff

collector = LlmAgent(
    model=build_model(),
    name="collector",
    description="Gathers every changed file's diff. Does not judge.",
    instruction=(
        "You gather material for a code review; you never judge it. You need the absolute path of a git "
        "repository, the base branch (assume 'main' if the person does not say) and the branch under "
        "review; ask for anything missing.\n\n"
        "Call inspect_repository, then changed_files, then show_diff for every changed file. Your final "
        "reply is the material itself and nothing else: for each file a heading `### <path>` followed "
        "by its diff in a fenced block. If a tool answers with an error, repeat its message and stop."
    ),
    tools=[inspect_repository, changed_files, show_diff],
    before_tool_callback=[only_changed_paths],
    on_model_error_callback=when_the_model_fails,
    output_key="diff",
)

reviewer = LlmAgent(
    model=build_model(),
    name="reviewer",
    description="Judges a diff and returns typed findings.",
    instruction=(
        "You are a careful code reviewer. Review the change below and report findings as the schema "
        "requires. Every finding must quote, verbatim, the diff lines it is about, and name a concrete "
        "fix. Report nothing you cannot point at in the diff; an empty findings list is a fine answer.\n\n"
        "## The change\n{diff}"
    ),
    # Only the instruction, which carries `{diff}`: the conversation would repeat the
    # collector's whole answer a second time, doubling the prompt for nothing.
    include_contents="none",
    generate_content_config=request_config(),
    before_agent_callback=without_evidence,
    on_model_error_callback=when_the_model_fails,
    output_schema=Review,
    output_key="review",
)

root_agent = Workflow(name="phase_4_first_review", edges=[("START", collector, reviewer)])
