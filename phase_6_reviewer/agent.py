"""Phase 6 — the reviewer's graph and its App, in two shapes.

In chat (`adk web`) an intake agent gathers the diff with the tools and puts
it in state, the lanes judge, and a verdict agent writes something readable.
From the CLI (`review.py`) the driver has already gathered the evidence in
plain Python and seeded state with it, so the graph is the lanes and the join
and nothing else: code, not a model, decides the verdict. The two shapes are
two graphs rather than one graph over seeded state because `output_key`
writes unconditionally — an intake agent run over seeded state would replace
the deterministic evidence with whatever it gathered itself.

`build_app` owns both the graph and the plugin roster, so a plugin added for
one shape is on the other. Both `root_agent` and `app` are exported: ADK's
loader looks for `app` first, and a bare `root_agent` would be wrapped in an
`App` without the plugins — an easy bug to ship.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.workflow import JoinNode, Workflow

from .config import build_model, request_config
from .lanes import LANE_NAMES, LANES, build_lane, state_key
from .plugins import RedactSecretsPlugin, ReportProviderErrors, UsageLedger
from .tools import changed_files, inspect_repository, only_changed_paths, show_diff

NAME = "phase_6_reviewer"
#: Three lanes hitting one key at once is what a free-tier quota tolerates.
LANE_CONCURRENCY = 3


def _intake() -> LlmAgent:
    return LlmAgent(
        model=build_model(),
        name="intake",
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
        output_key="diff",
    )


def _verdict() -> LlmAgent:
    # `{key?}`: optional, empty when the lane wrote nothing. Measured without it: a lane that failed ended as its own
    # event, the graph went on, and this agent raised `KeyError` on the missing key — a traceback in `adk web` after
    # all, from the one agent that runs after the failure.
    sections = "\n\n".join(f"## {name}\n{{{state_key(name)}?}}" for name in LANE_NAMES)
    return LlmAgent(
        model=build_model(),
        name="verdict",
        description="Combines the lanes' findings into one readable verdict, for chat.",
        instruction=(
            "Reviewers have judged one change. Write the verdict as markdown: a one-line verdict "
            "(APPROVED, or REQUEST CHANGES if any finding is major or blocker), then every finding grouped "
            "under its lane with its file, severity, title and the evidence quoted. A section below that is "
            "empty is a lane that failed; one whose summary says nothing was gathered is a lane that did not "
            "look. In either case say so under its heading, and never approve what was not judged. Add "
            f"nothing of your own.\n\n{sections}"
        ),
        include_contents="none",
        generate_content_config=request_config(),
        output_key="verdict",
    )


def build_workflow(*, chat: bool) -> Workflow:
    """The graph: intake → lanes → join → verdict for chat; lanes → join for the CLI, which seeds state itself.

    Agents are built per call: an agent object belongs to one parent.
    """
    lanes = tuple(build_lane(*lane) for lane in LANES)
    join = JoinNode(name="join_lanes")
    edge = ("START", _intake(), lanes, join, _verdict()) if chat else ("START", lanes, join)
    return Workflow(name=NAME, edges=[edge], max_concurrency=LANE_CONCURRENCY)


def build_app(*, chat: bool) -> App:
    """The graph under the plugins no agent can opt out of."""
    plugins = [RedactSecretsPlugin(), UsageLedger(), ReportProviderErrors()]
    return App(name=NAME, root_agent=build_workflow(chat=chat), plugins=plugins)


app = build_app(chat=True)
root_agent = app.root_agent
