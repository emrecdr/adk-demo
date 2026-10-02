"""Every phase loads the way `adk web .` loads it, on both arms, and answers through the real engine."""

from __future__ import annotations

import importlib
import sys
from contextlib import suppress

import pytest
from conftest import PHASES, ROOT, judge_module, load_phase, run_turn
from google.adk.cli.utils.agent_loader import AgentLoader
from google.adk.models.lite_llm import LiteLlm

EXPECTED = [
    "phase_1_hello_world",
    "phase_2_preflight",
    "phase_3_changed_files",
    "phase_4_first_review",
    "phase_5_parallel_lanes",
    "phase_6_reviewer",
    "phase_7_hardened",
]


@pytest.mark.parametrize("phase", EXPECTED)
def test_the_loader_lists_it_and_the_agent_is_named_after_its_folder(phase: str, monkeypatch) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("REVIEW_PROVIDER", "gemini")
    loader = AgentLoader(agents_dir=".")
    assert phase in loader.list_agents()
    loaded = loader.load_agent(phase)  # an App when the phase exports one, else the agent
    assert getattr(loaded, "root_agent", loaded).name == phase


def test_adk_web_lists_the_phases_and_nothing_else(monkeypatch) -> None:
    """`adk web` uses ADK's nested loader, not the flat one `adk run` and the test above use: any folder holding an
    `agent.py`, five levels down, is an agent of its own. Measured in the browser: phase 7's graph module, then
    `judge/agent.py`, put `phase_7_hardened.judge` in the dropdown, and choosing it failed with no `root_agent`."""
    from google.adk.cli.utils._nested_agent_loader import NestedAgentLoader

    monkeypatch.chdir(ROOT)
    assert sorted(NestedAgentLoader(".").list_agents()) == EXPECTED


@pytest.mark.parametrize("phase", [p for p in PHASES if (ROOT / p / "review.py").is_file()])
def test_a_phase_that_is_also_a_command_imports_nothing_at_its_root(phase: str, monkeypatch) -> None:
    """`python -m <phase>.review` imports the package before the command's `main` reads the root `.env`, and
    `agent.py` builds its agents when it is imported. Measured with the scaffold's `from . import agent` kept:
    `.env` named Copilot and the command's collector was built on Gemini. The loader test above is the other
    half: `adk web` finds `agent.py` without the line."""
    for name in [m for m in sys.modules if m == phase or m.startswith(f"{phase}.")]:
        monkeypatch.delitem(sys.modules, name)
    importlib.import_module(phase)
    assert f"{phase}.agent" not in sys.modules


@pytest.mark.parametrize("phase", EXPECTED)
@pytest.mark.parametrize(
    ("provider", "expected"),
    [("gemini", str), ("copilot", LiteLlm), (None, LiteLlm), ("", LiteLlm), ("  ", LiteLlm)],
)
def test_both_arms_build_a_model(phase: str, provider: str | None, expected: type, monkeypatch) -> None:
    """Gemini is a native model string; everything else is LiteLlm. One variable decides, and names Copilot, the arm
    the talk is given on and the team runs on, when it names none: left out, or left blank as a blank `REVIEW_MODEL=`
    is the default model. Measured by review: python-dotenv reads `REVIEW_PROVIDER=` as the empty string, and every
    phase refused it as no provider at all."""
    if provider is None:
        monkeypatch.delenv("REVIEW_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("REVIEW_PROVIDER", provider)
    monkeypatch.delenv("REVIEW_MODEL", raising=False)
    name = judge_module(phase, "config")
    sys.modules.pop(name, None)
    assert isinstance(importlib.import_module(name).build_model(), expected)


@pytest.mark.parametrize(
    "phase", ["phase_4_first_review", "phase_5_parallel_lanes", "phase_6_reviewer", "phase_7_hardened"]
)
def test_every_judging_agent_reads_only_its_instruction_at_temperature_zero(phase: str, monkeypatch) -> None:
    """A lane's prompt is its instruction with `{diff}` in it; the conversation would repeat the
    diff a second time. And a severity is a decision, so the judging agents sample at zero."""
    from google.adk.agents import LlmAgent

    entry = load_phase(monkeypatch, phase)
    module = sys.modules[entry.build_app.__module__] if hasattr(entry, "build_app") else entry  # the graph's own
    if hasattr(module, "_verdict"):  # a graph: every LlmAgent in it judges but the intake, which gathers
        judges = [n for n in entry.root_agent.graph.nodes if isinstance(n, LlmAgent) and n.name != "intake"]
        with suppress(ModuleNotFoundError):  # phase 7's fourth judging agent, in a graph of its own
            judges.append(importlib.import_module(judge_module(phase, "verify")).build_verifier(0))
    else:
        judges = list(getattr(module, "lanes", [])) or [module.reviewer]
        judges += [module.verdict] if hasattr(module, "verdict") else []
    for agent in judges:
        assert agent.include_contents == "none", agent.name
        assert agent.generate_content_config is not None and agent.generate_content_config.temperature == 0.0, (
            agent.name
        )


@pytest.mark.parametrize("phase", EXPECTED[2:])  # phase 3 is the first with a path to guard
def test_every_agent_with_tools_carries_the_path_guardrail(phase: str, monkeypatch) -> None:
    """A tool argument is untrusted input from phase 3 on. test_callbacks proves the callback; this pins that
    every agent that can call show_diff actually has it attached, in whatever graph the phase builds."""
    from google.adk.agents import LlmAgent

    module = load_phase(monkeypatch, phase)
    root = module.root_agent
    agents = [n for n in root.graph.nodes if isinstance(n, LlmAgent)] if hasattr(root, "graph") else [root]
    armed = [a for a in agents if a.tools]
    assert armed, "no agent with tools in this phase"
    for agent in armed:
        callbacks = agent.before_tool_callback
        callbacks = callbacks if isinstance(callbacks, list) else [callbacks] if callbacks else []
        assert "only_changed_paths" in [cb.__name__ for cb in callbacks], agent.name


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", EXPECTED)
async def test_it_answers_through_the_real_engine_with_a_fake_model(phase: str, monkeypatch) -> None:
    module = load_phase(monkeypatch, phase)
    final, _state = await run_turn(module, "hello")
    assert final, "no final response reached the runner"


def test_the_suite_reads_neither_the_developers_env_nor_the_network() -> None:
    """LiteLLM, in its default mode, reads the nearest `.env` into the process when imported, and fetches its model
    map from the network. Measured: the suite took five keys from the developer's `.env` into every test, and every
    import tried the network first. `.env.example` offers every run the second switch."""
    import os

    assert os.environ.get("LITELLM_MODE") == "PRODUCTION"
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"
    assert "\nLITELLM_LOCAL_MODEL_COST_MAP=True\n" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_no_test_inherits_a_provider_or_a_model_from_the_shell() -> None:
    """A developer's own `REVIEW_PROVIDER=copilot` or `REVIEW_VERIFIER_MODEL` would send a test to a real model."""
    import os

    assert not [name for name in os.environ if name.startswith("REVIEW_") or name == "GOOGLE_GENAI_USE_VERTEXAI"]
