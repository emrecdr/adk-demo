"""A provider error is a sentence from phase 4 on, never a traceback — each agent's own hook, then the plugin from
phase 6 — and nothing judges what was never gathered. Phases 1 to 3 stay the smallest agents and let it through."""

from __future__ import annotations

import importlib
import sys

import litellm
import pytest
from conftest import PHASES, QUOTA_TEXT, REVIEW_REQUEST, ROOT, judge_module, load_phase, quota, run_turn

SENTENCE = f"I could not reach the model: RuntimeError: {QUOTA_TEXT}"
HOOKED = PHASES[PHASES.index("phase_4_first_review") :]  # from here on: the hook, and a gatherer before reviewers
BARE = [p for p in PHASES if p not in HOOKED]  # the smallest agents carry no hook: the two lists partition PHASES
JOINED = PHASES[PHASES.index("phase_5_parallel_lanes") :]  # a verdict after the lanes


def _lanes(state: dict) -> dict:
    return {k: v for k, v in state.items() if k.startswith("lane_") or k == "review"}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", BARE)
async def test_before_phase_4_a_provider_error_is_adks_own(phase, monkeypatch, fake_provider):
    """The smallest agents carry no hook, by choice: the error reaches the runner as ADK raises it, and the
    traceback's last line is the reason, as the README promises."""
    module = load_phase(monkeypatch, phase)
    fake_provider.raises_when("", quota())
    with pytest.raises(RuntimeError) as escaped:
        await run_turn(module, REVIEW_REQUEST)
    assert escaped.exconly() == f"RuntimeError: {QUOTA_TEXT}", "the traceback's last line is the reason"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", HOOKED)
async def test_when_every_call_fails_the_answer_names_the_error_and_nothing_raises(phase, monkeypatch, fake_provider):
    """Measured on Gemini's free tier before this: `adk run` printed sixty lines of traceback for a 429."""
    module = load_phase(monkeypatch, phase)
    fake_provider.raises_when("", quota())  # every instruction contains the empty string: every call fails
    final, state = await run_turn(module, REVIEW_REQUEST)
    assert QUOTA_TEXT in final, final
    assert all(v["findings"] == [] for v in _lanes(state).values()), "nothing was judged"
    assert not [k for k in state if k.startswith("temp:")], "the note lives for one invocation, not the session"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", HOOKED)
async def test_when_the_gatherer_fails_no_reviewer_judges_and_each_says_why(phase, monkeypatch, fake_provider):
    """The gatherer's answer is a sentence, not a diff: a reviewer run over it would find nothing, and "did not
    look" must never read as "found nothing". Measured before the guard: `KeyError` on the missing `diff`."""
    module = load_phase(monkeypatch, phase)
    fake_provider.raises_when("gather material", quota())
    final, state = await run_turn(module, REVIEW_REQUEST)
    assert final, "the last agent answered"
    lanes = _lanes(state)
    assert lanes and all(
        v["findings"] == [] and "Nothing was gathered" in v["summary"] and QUOTA_TEXT in v["summary"]
        for v in lanes.values()
    ), "nothing judged, and each says why"
    if phase in JOINED:
        assert state["verdict"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", JOINED)
async def test_when_one_lane_fails_the_others_finish_and_the_verdict_still_answers(phase, monkeypatch, fake_provider):
    """The one agent that runs after a failed lane must not die on its missing key. Phase 5's lane answers its
    schema with the sentence; from phase 6 the plugin answers nothing for a lane, so the key is a hole the
    command names — in chat, the verdict reads it as an empty section."""
    module = load_phase(monkeypatch, phase)
    fake_provider.raises_when("tests are honest", quota())
    final, state = await run_turn(module, REVIEW_REQUEST)
    assert final and state["verdict"], "the verdict agent answered"
    assert state["lane_security"]["findings"], "the other lanes finished"
    if phase == "phase_5_parallel_lanes":
        assert state["lane_tests"]["findings"] == [] and SENTENCE in state["lane_tests"]["summary"]
    else:
        assert "lane_tests" not in state, "a hole, for the code that decides"


@pytest.mark.parametrize("phase", [BARE[0], HOOKED[0]])
def test_the_ask_script_prints_a_failure_as_one_line_either_way(phase, monkeypatch, fake_provider, capsys, tmp_path):
    """Its docstring's two promises: a failed agent's own error event is printed by name, and what escapes the engine
    — a provider error where no hook catches it — is one line and exit 3, never a traceback. Measured: on a bare
    phase the runner emits an error event for the agent before it re-raises, so the reason is printed twice."""
    load_phase(monkeypatch, phase)
    fake_provider.raises_when("", quota())
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    ask = importlib.import_module("ask")
    monkeypatch.setattr(ask, "ROOT", tmp_path)  # no `.env` there: the fake stays the model, no key enters the process
    code = ask.main([phase, REVIEW_REQUEST])
    out, err = capsys.readouterr()
    if phase in BARE:
        assert code == 3 and not out
        by_name, escaped = f"[error] {phase}: RuntimeError: {QUOTA_TEXT}", f"ask: RuntimeError: {QUOTA_TEXT}"
        assert err.splitlines() == [by_name, escaped], "the runner's event, then the traceback's last line"
    else:
        assert code == 0 and QUOTA_TEXT in out, "the agent answered, with the reason"
        assert f"[error] collector: RuntimeError: {QUOTA_TEXT}" in err, "the failed agent's own event, by name"


@pytest.mark.parametrize(
    "phase", ["phase_4_first_review", "phase_5_parallel_lanes", "phase_6_reviewer", "phase_7_hardened"]
)
def test_litellms_banner_is_turned_off_where_the_copilot_arm_is_built(phase: str, monkeypatch) -> None:
    """LiteLLM prints a red "Give Feedback" banner on stdout with every error it maps. The arm it serves, and only
    that arm, imports it and turns the banner off as its model is built: measured at the top of a command, the
    import cost about a second of every start and fetched a price list."""
    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    monkeypatch.setenv("REVIEW_PROVIDER", "copilot")
    importlib.import_module(judge_module(phase, "config")).build_model()
    assert litellm.suppress_debug_info


def test_the_ask_script_turns_litellms_banner_off_on_the_copilot_arm_alone(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    ask = importlib.import_module("ask")
    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    monkeypatch.setenv("REVIEW_PROVIDER", "gemini")
    ask._quiet_litellm()
    assert not litellm.suppress_debug_info, "on the Gemini arm LiteLLM is never asked for"
    monkeypatch.delenv("REVIEW_PROVIDER")
    ask._quiet_litellm()
    assert litellm.suppress_debug_info, "Copilot is the arm when none is named"
    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    monkeypatch.setenv("REVIEW_PROVIDER", "")
    ask._quiet_litellm()
    assert litellm.suppress_debug_info, "nor when it is left blank"


def test_a_providers_error_is_one_readable_line_from_phase_4_on() -> None:
    """genai's `str` is the whole JSON body; its `.message` is the sentence; LiteLLM's `.message` carries its class as
    a prefix and its code as `.status_code`. The same line from either arm, from phase 4 to 7."""
    from google.genai import errors

    from phase_4_first_review.config import describe as first
    from phase_7_hardened.judge.plugins import describe as last

    message = "You exceeded your current quota. Please retry in 19s."
    spent = errors.ClientError(429, {"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}})
    assert first(spent) == last(spent) == f"429: {message}", "the status is the error code, not the message"
    limited = litellm.exceptions.RateLimitError("Rate limit reached", llm_provider="github_copilot", model="gpt-4.1")
    assert first(limited) == last(limited) == "429: Rate limit reached", "the class prefix goes, the code stays"
    assert first(RuntimeError("x\n y")) == "x y", "no code, so the text alone; the caller adds the class"
    assert first(RuntimeError("z" * 1000)).endswith("[… cut at 400 characters]")


@pytest.mark.parametrize("phase", HOOKED)
def test_an_error_nothing_named_is_a_sentence_and_exit_3_never_a_verdict(phase: str, monkeypatch, capsys) -> None:
    """Python ends an uncaught exception with exit 1, the code for "a blocker was found". Measured before: errors
    found and named one at a time, six recorded in the design record and a seventh by review, each ended in a
    traceback and exit 1. Now any error nothing else named is a review that did not finish: a sentence, exit 3."""
    module = importlib.import_module(f"{phase}.review")

    def unforeseen(*_args, **_kwargs):
        raise RuntimeError("something nothing named")

    monkeypatch.setattr(module, "build_parser", unforeseen)
    assert module.main(["--head", "x"]) == 3
    err = capsys.readouterr().err
    assert "the review did not finish: RuntimeError: something nothing named" in err and "Traceback" not in err, err


@pytest.mark.parametrize("entry", [*HOOKED, "ask"])
def test_a_dot_env_that_is_not_utf8_is_a_sentence_and_exit_2(entry: str, monkeypatch, tmp_path, capsys) -> None:
    """Windows PowerShell 5.1's `>` writes UTF-16. Measured before: a `.env` written that way ended every command in
    a `UnicodeDecodeError` traceback and exit 1, the code for "a blocker was found"."""
    (tmp_path / ".env").write_text("REVIEW_PROVIDER=copilot\n", encoding="utf-16")
    if entry == "ask":
        monkeypatch.syspath_prepend(str(ROOT / "scripts"))
        module, argv = importlib.import_module("ask"), ["phase_1_hello_world", "hi"]
    else:
        module, argv = importlib.import_module(f"{entry}.review"), ["--head", "x"]
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main(argv) == 2
    err = capsys.readouterr().err
    assert ".env is not UTF-8" in err and "Traceback" not in err, err


@pytest.mark.parametrize("phase", HOOKED)
def test_a_misspelt_provider_is_a_sentence_and_exit_2_from_every_command(phase: str) -> None:
    """Measured before: phase 6 built its chat graph at import, so `REVIEW_PROVIDER=gemni` raised there — a
    traceback and Python's exit 1, the code for "a blocker was found" — before the readiness check could answer."""
    import os
    import subprocess

    env = {**os.environ, "REVIEW_PROVIDER": "gemni", "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
    done = subprocess.run(
        [sys.executable, "-m", f"{phase}.review", "--head", "x"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert done.returncode == 2, done.stderr[-400:]
    assert "REVIEW_PROVIDER must be one of" in done.stderr and "'gemni'" in done.stderr, done.stderr[-400:]
    assert "Traceback" not in done.stderr, done.stderr[-400:]


@pytest.mark.parametrize("phase", ["phase_6_reviewer", "phase_7_hardened"])
def test_the_report_names_the_model_that_ran(phase: str, monkeypatch) -> None:
    """Every entry point lets the shell's variables win over `.env`, so a stale export picks the arm or the model
    unseen: the report names both, and Vertex AI when the environment sends the Gemini arm there."""
    load_phase(monkeypatch, phase)
    config = importlib.import_module(
        "phase_6_reviewer.config" if phase == "phase_6_reviewer" else f"{phase}.judge.config"
    )
    monkeypatch.setenv("REVIEW_PROVIDER", "gemini")
    assert config.serving() == "fake on gemini"
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    assert config.serving() == "fake on gemini through Vertex AI"


@pytest.mark.parametrize("phase", ["phase_6_reviewer", "phase_7_hardened"])
def test_an_empty_copilot_token_is_no_token(phase: str, monkeypatch, tmp_path) -> None:
    """Measured before: an empty token file passed the readiness check, and LiteLLM began its own device login
    inside the first model call, three minutes, its code printed where no one was looking."""
    load_phase(monkeypatch, phase)
    (tmp_path / "access-token").write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path))
    monkeypatch.setenv("REVIEW_PROVIDER", "copilot")
    why = importlib.import_module(judge_module(phase, "config")).require_ready()
    assert why and "needs a cached token" in why, why


@pytest.mark.parametrize("phase", ["phase_6_reviewer", "phase_7_hardened"])
def test_the_copilot_token_never_reaches_a_log(phase: str, monkeypatch, caplog) -> None:
    """LiteLLM's debug dump masks a request's headers and prints its body whole, and the Copilot arm carries its
    token in the body's `extra_headers`. Measured with a fake token: `adk web -v` logged it whole."""
    import logging

    load_phase(monkeypatch, phase)
    monkeypatch.setenv("REVIEW_PROVIDER", "copilot")
    importlib.import_module(judge_module(phase, "config")).build_model()
    with caplog.at_level(logging.DEBUG, logger="LiteLLM"):
        logging.getLogger("LiteLLM").debug("-d '%s'", '{"extra_headers": {"Authorization": "Bearer tid=abc123;exp=9"}}')
    assert "tid=abc123" not in caplog.text and "Bearer [REDACTED]" in caplog.text, caplog.text


def test_the_copilot_login_reads_an_empty_token_file_as_none(tmp_path, monkeypatch, capsys) -> None:
    """Phases 6 and 7 call an empty token file no token and say to run the login; found by review, the login then
    answered "already authenticated" and logged no one in."""
    import copilot_login
    from litellm.llms.github_copilot import authenticator

    (tmp_path / "access-token").write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path))
    monkeypatch.delenv("GITHUB_COPILOT_ACCESS_TOKEN_FILE", raising=False)

    def began(_self):  # the device flow's first request: no network in the suite
        raise RuntimeError("the login began")

    monkeypatch.setattr(authenticator.Authenticator, "_get_device_code", began)
    with pytest.raises(RuntimeError, match="the login began"):
        copilot_login.main([])
    assert "already authenticated" not in capsys.readouterr().out


@pytest.mark.skipif(sys.platform == "win32", reason="a Windows file has no owner/group/other modes to narrow")
def test_the_copilot_login_keeps_its_files_to_their_owner(tmp_path) -> None:
    """Measured before: both token files 0644 in a 0755 directory, readable by every account on the machine."""
    import copilot_login

    (tmp_path / "access-token").write_text("t", encoding="utf-8")
    (tmp_path / "api-key.json").write_text("{}", encoding="utf-8")
    for path in (tmp_path, *tmp_path.iterdir()):
        path.chmod(0o755 if path.is_dir() else 0o644)
    copilot_login.keep_private(tmp_path)
    assert oct(tmp_path.stat().st_mode & 0o777) == "0o700"
    assert {oct(path.stat().st_mode & 0o777) for path in tmp_path.iterdir()} == {"0o600"}


@pytest.mark.parametrize("phase", ["phase_6_reviewer", "phase_7_hardened"])
@pytest.mark.parametrize(("arm", "said"), [("gemini", "needs GOOGLE_API_KEY"), ("copilot", "needs a cached token")])
def test_an_arm_that_cannot_run_is_a_sentence(phase: str, arm: str, said: str, monkeypatch, tmp_path) -> None:
    """Measured by coverage: neither refusal ran in a test. A key missing, or no token cached, is named before
    anything is spent."""
    load_phase(monkeypatch, phase)
    monkeypatch.setenv("REVIEW_PROVIDER", arm)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path))
    why = importlib.import_module(judge_module(phase, "config")).require_ready()
    assert why and said in why, why
