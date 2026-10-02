"""Phase 5 — parallel lanes.

Three specialised reviewers judge the same diff at once. In the edge, an inner
tuple is a fan-out, `JoinNode` waits for every branch, and the agent after the
join reads all three answers from state. Each lane is built by one factory
from a three-line table — name, role, thinking budget — so adding a lane is a
row, not a file. The provider is still the only provider-specific line of
code, in `config.py`; `lane_planner` is the one thing that differs by arm.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.workflow import JoinNode, Workflow

from .callbacks import only_changed_paths, without_evidence
from .config import build_model, lane_planner, request_config, when_the_model_fails
from .schemas import Review
from .tools import changed_files, inspect_repository, show_diff

#: (name, role, thinking budget). Adding a lane is a row.
LANES = (
    ("security", "You judge the change for security defects and unsafe patterns.", 4096),
    (
        "tests",
        "You judge the tests: whether what the change adds is tested at all, and whether the tests are honest: "
        "real behaviour, realistic inputs, no over-mocking.",
        4096,
    ),
    ("complexity", "You judge whether the change is more complex than the problem requires.", 2048),
)

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


def build_lane(name: str, role: str, thinking_budget: int) -> LlmAgent:
    """One reviewer: a role, the shared diff, the shared schema, its own budget."""
    return LlmAgent(
        model=build_model(),
        name=f"lane_{name}",
        description=f"Reviews the {name} dimension of the change.",
        instruction=(
            f"{role} Review the change below and report findings as the schema requires, only in your "
            "dimension. Severity is a scale, not a mood: blocker means the change must not merge (an exploitable "
            "vulnerability, data loss); major means a real bug or vulnerability to fix before merge; minor means "
            "hardening, style, or a missing test. Advice that would merely make good code better is minor. "
            "Every finding must quote, verbatim, the diff lines it is about, and name a concrete "
            "fix. Report nothing you cannot point at in the diff; an empty findings list is a fine answer.\n\n"
            "## The change\n{diff}"
        ),
        planner=lane_planner(thinking_budget),
        # Only the instruction, which carries `{diff}`: the conversation would repeat it.
        include_contents="none",
        generate_content_config=request_config(),
        before_agent_callback=without_evidence,
        on_model_error_callback=when_the_model_fails,
        output_schema=Review,
        output_key=f"lane_{name}",
    )


lanes = tuple(build_lane(*lane) for lane in LANES)
join = JoinNode(name="join_lanes")

# `{key?}`: optional, empty when the lane wrote nothing — an answer with no content, blocked or empty; a provider
# error is answered in the schema above and always writes. Derived from the table: adding a lane is a row.
sections = "\n\n".join(f"## {name}\n{{lane_{name}?}}" for name, _role, _budget in LANES)

verdict = LlmAgent(
    model=build_model(),
    name="verdict",
    description="Combines the three lanes' findings into one verdict.",
    instruction=(
        "Three reviewers have judged one change. Write the verdict as markdown: a one-line verdict "
        "(APPROVED, or REQUEST CHANGES if any finding is major or blocker), then every finding grouped "
        "under its lane with its file, severity, title and the evidence quoted. A section below that is "
        "empty is a lane that failed; one whose summary says nothing was gathered or that the model could not "
        "be reached is a lane that did not look. In either case say so under its heading, and never approve "
        f"what was not judged. Add nothing of your own.\n\n{sections}"
    ),
    include_contents="none",
    generate_content_config=request_config(),
    on_model_error_callback=when_the_model_fails,
    output_key="verdict",
)

root_agent = Workflow(
    name="phase_5_parallel_lanes",
    edges=[("START", collector, lanes, join, verdict)],
    # Three lanes hitting one key at once is what a free-tier quota tolerates.
    max_concurrency=3,
)
