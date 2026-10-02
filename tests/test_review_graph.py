"""The review graphs, driven through the real engine with a fake model: typed findings land in state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import CANNED_REVIEW, QUOTA_TEXT, REVIEW_REQUEST, load_phase, quota, run_review, run_turn


class TestPhase4:
    def test_the_schema_accepts_a_well_formed_review_and_refuses_a_bad_severity(self) -> None:
        from pydantic import ValidationError

        from phase_4_first_review.schemas import Review

        review = Review.model_validate(CANNED_REVIEW)
        assert review.findings[0].severity == "major"
        bad = {**CANNED_REVIEW, "findings": [{**CANNED_REVIEW["findings"][0], "severity": "catastrophic"}]}
        with pytest.raises(ValidationError):
            Review.model_validate(bad)

    @pytest.mark.asyncio
    async def test_collector_then_reviewer_leaves_a_typed_review_in_state(self, monkeypatch) -> None:
        """One sequential edge: the collector's text lands under `diff`, the reviewer's
        schema'd answer lands under `review` as a dict, not as text."""
        module = load_phase(monkeypatch, "phase_4_first_review")
        _final, state = await run_turn(module, REVIEW_REQUEST)
        assert "diff" in state, "the collector's output_key"
        assert isinstance(state["review"], dict), "output_schema puts a dict in state"
        assert state["review"]["findings"][0]["title"].startswith("shell=True")


class TestPhase5:
    def test_the_thinking_budget_exists_on_gemini_and_not_on_copilot(self, monkeypatch) -> None:
        import importlib
        import sys

        from google.adk.planners import BuiltInPlanner

        sys.modules.pop("phase_5_parallel_lanes.config", None)
        config = importlib.import_module("phase_5_parallel_lanes.config")
        monkeypatch.setenv("REVIEW_PROVIDER", "gemini")
        planner = config.lane_planner(2048)
        assert isinstance(planner, BuiltInPlanner) and planner.thinking_config.thinking_budget == 2048
        monkeypatch.setenv("REVIEW_PROVIDER", "copilot")
        assert config.lane_planner(2048) is None, "the lever does not exist on that arm"

    @pytest.mark.asyncio
    async def test_three_lanes_fan_out_join_and_a_verdict_reads_all_three(self, monkeypatch) -> None:
        module = load_phase(monkeypatch, "phase_5_parallel_lanes")
        assert [lane.name for lane in module.lanes] == ["lane_security", "lane_tests", "lane_complexity"]
        _final, state = await run_turn(module, REVIEW_REQUEST)
        for name in ("lane_security", "lane_tests", "lane_complexity"):
            assert isinstance(state[name], dict) and state[name]["findings"], name
        assert state["verdict"], "the agent after the join answered"


class TestPhase4Command:
    """The same graph as a command: the arguments make the message, the typed review is printed, and the exit code
    says how the run went — never 0 for a run that did not look."""

    def test_the_command_prints_the_typed_review_and_exits_0(self, demo_repo: Path, phase4_review, capsys) -> None:
        assert run_review(phase4_review, demo_repo) == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["findings"] == CANNED_REVIEW["findings"] and err == ""

    def test_a_branch_that_does_not_exist_is_exit_2_before_any_model_call(
        self, demo_repo: Path, phase4_review, fake_provider, capsys
    ) -> None:
        fake_provider.raises_when("", AssertionError("a model was called"))
        assert phase4_review.main([str(demo_repo), "--head", "no-such-branch"]) == 2
        assert "no-such-branch" in capsys.readouterr().err

    def test_a_provider_that_fails_is_exit_3_with_the_agent_named(
        self, demo_repo: Path, phase4_review, fake_provider, capsys
    ) -> None:
        fake_provider.raises_when("gather material", quota())
        assert run_review(phase4_review, demo_repo) == 3
        out, err = capsys.readouterr()
        assert f"review: collector: RuntimeError: {QUOTA_TEXT}" in err
        assert "Nothing was gathered" in json.loads(out)["summary"], "printed, and it says why it judged nothing"


class TestPhase5Command:
    """Phase 4's command with the verdict agent's first line as the exit code; a failed lane wins over it."""

    @pytest.mark.parametrize(("word", "code"), [("APPROVED", 0), ("REQUEST CHANGES", 1)])
    def test_the_verdicts_first_line_is_the_exit_code(
        self, demo_repo: Path, phase5_review, fake_provider, capsys, word: str, code: int
    ) -> None:
        fake_provider.answers_when("Three reviewers have judged", f"{word}\n\n## security\n- one finding\n")
        assert run_review(phase5_review, demo_repo) == code
        assert capsys.readouterr().out.startswith(word)

    def test_a_lane_that_failed_is_exit_3_whatever_the_verdict_says(
        self, demo_repo: Path, phase5_review, fake_provider, capsys
    ) -> None:
        fake_provider.raises_when("tests are honest", quota())
        fake_provider.answers_when("Three reviewers have judged", "APPROVED\n")
        assert run_review(phase5_review, demo_repo) == 3
        assert f"review: lane_tests: RuntimeError: {QUOTA_TEXT}" in capsys.readouterr().err

    def test_a_verdict_that_names_no_verdict_is_exit_3(self, demo_repo: Path, phase5_review, capsys) -> None:
        """The fake's default prose says neither word; the command does not guess."""
        assert run_review(phase5_review, demo_repo) == 3
        assert "names no verdict" in capsys.readouterr().err
