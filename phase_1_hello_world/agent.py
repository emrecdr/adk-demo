"""Phase 1 — hello world.

The smallest legal ADK agent: one `Agent` (an alias of `LlmAgent`) with a
model, a name and an instruction. No tools, no state, no callbacks. `root_agent`
is the name the ADK loader looks for; the folder name is the agent's name, so
what `adk web .` lists is what this code says.
"""

from __future__ import annotations

from google.adk.agents import Agent

from .config import build_model

root_agent = Agent(
    model=build_model(),
    name="phase_1_hello_world",
    description="Greets, and says what a review agent would need. No tools.",
    instruction=(
        "You are the first step of a demo about building a code reviewer with Google ADK. "
        "Greet the person in one sentence. Then, in two sentences, say what you would need "
        "in order to review a git branch. You have no tools yet, so say so plainly."
    ),
)
