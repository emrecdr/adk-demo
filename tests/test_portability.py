"""What has to hold for the demo to run on Windows as well as macOS, pinned by reading the source."""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import PHASES, ROOT, _git_in

SOURCES = list(ROOT.glob("phase_*/**/*.py")) + list((ROOT / "scripts").glob("*.py"))


def _subprocess_calls(path: Path):
    """Real `subprocess.run(...)` calls, read off the syntax tree — not the ones the demo repository plants as text."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
        ):
            yield node


def test_every_subprocess_decodes_utf8_explicitly() -> None:
    """A Windows console is a code page, git's output is UTF-8, and `text=True` alone
    would decode a path or a diff with the console's encoding and fail. Any keyword that
    turns decoding on (`text`, `universal_newlines`, `errors`) must come with `encoding`.
    A call that stays in bytes decodes nothing, and its caller names the encoding: the
    blast radius reads blobs that way, because git counts their sizes in bytes."""
    offenders = [
        f"{path.relative_to(ROOT)}:{call.lineno}"
        for path in SOURCES
        for call in _subprocess_calls(path)
        if {kw.arg for kw in call.keywords} & {"text", "universal_newlines", "errors"}
        and not any(kw.arg == "encoding" for kw in call.keywords)
    ]
    assert offenders == [], offenders


def test_no_phase_or_script_assumes_a_posix_temp_directory() -> None:
    offenders = [str(p.relative_to(ROOT)) for p in SOURCES if "/tmp/" in p.read_text(encoding="utf-8")]
    assert offenders == [], "use tempfile.gettempdir(): " + ", ".join(offenders)


def test_the_demo_repo_default_is_the_platform_temp_dir(monkeypatch, tmp_path: Path) -> None:
    import make_demo_repo

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert make_demo_repo.main([]) == 0
    assert (tmp_path / "adk-demo-repo" / ".git").is_dir()


def test_the_demo_repo_script_builds_nothing_for_a_flag_it_does_not_know(monkeypatch, capsys) -> None:
    """Measured before: `--help`, or any flag misspelt, was ignored and the demo repository rebuilt, a rehearsal's
    `--fix` commits lost with it."""
    import make_demo_repo

    def refuse(*_args):
        raise AssertionError("built")

    monkeypatch.setattr(make_demo_repo, "build", refuse)
    monkeypatch.setattr(make_demo_repo, "fix", refuse)
    for argv, code in ((["--help"], 0), (["--fx"], 2)):
        with pytest.raises(SystemExit) as stopped:
            make_demo_repo.main(argv)
        assert stopped.value.code == code, argv
    assert "--fix" in capsys.readouterr().out, "the help names the flags"


def test_the_review_command_defaults_to_the_same_demo_repository(monkeypatch) -> None:
    """The phase-6 command's positional defaults to the repository `make_demo_repo.py` builds, spelled the same way."""
    monkeypatch.setenv("REVIEW_PROVIDER", "gemini")
    from phase_6_reviewer.review import DEMO_REPO

    assert Path(DEMO_REPO) == Path(tempfile.gettempdir()) / "adk-demo-repo"


def test_every_phase_is_an_importable_identifier() -> None:
    """`adk web .` imports each folder as a package; a hyphen or a leading digit would break it on every OS."""
    assert all(p.isidentifier() for p in PHASES), PHASES


def test_the_rehearsal_names_every_phase_and_runs_nothing_when_told(capsys) -> None:
    import rehearse

    assert rehearse.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert all(phase in out for phase in PHASES), "every phase has a demo line"
    assert "--verify" in out and "--max-tokens" in out and "make_demo_repo" in out


def test_every_command_that_prints_a_report_writes_utf8_whatever_the_console() -> None:
    """A Windows console is a code page, and a report holds an em dash: each command and `ask.py` reconfigures
    stdout. Measured before: the docs said two scripts did, five do, and no test read any of them."""
    scripts = ("ask.py", "make_demo_repo.py", "rehearse.py", "copilot_login.py")
    printers = [*(ROOT / "scripts" / name for name in scripts), *(ROOT / phase / "review.py" for phase in PHASES)]
    missing = [
        str(path.relative_to(ROOT))
        for path in printers
        if path.is_file() and 'sys.stdout.reconfigure(encoding="utf-8"' not in path.read_text(encoding="utf-8")
    ]
    assert len([path for path in printers if path.is_file()]) == 8 and missing == [], missing


@pytest.fixture
def signing_git_config(tmp_path: Path, monkeypatch) -> None:
    """A developer's global config that signs every commit, with a signer that always fails."""
    config = tmp_path / "gitconfig"
    config.write_text("[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


@pytest.mark.usefixtures("signing_git_config")
def test_the_demo_repository_builds_and_rebuilds_whatever_the_builders_git_config(tmp_path: Path) -> None:
    """Measured before: a global `commit.gpgsign = true` failed the build, run as a presenter runs it. It is rebuilt
    into the same folder too, whose git objects are read-only, which Windows will not delete as they are."""
    import subprocess
    import sys

    root = tmp_path / "repo"
    for _build in range(2):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_demo_repo.py"), str(root)],
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-300:]
    assert (root / ".git").is_dir()


@pytest.mark.usefixtures("signing_git_config")
def test_the_test_fixtures_build_whatever_the_developers_git_config(tmp_path: Path) -> None:
    """Measured before: the same config failed every fixture's commit, so the suite failed on a signing machine."""
    _git_in(tmp_path, "init", "-q")
    _git_in(tmp_path, "commit", "-q", "--allow-empty", "-m", "x")
    assert _git_in(tmp_path, "rev-list", "--count", "HEAD") == "1"


def test_no_rehearsed_step_stops_at_phase_7s_question() -> None:
    """With neither `--base` nor `--all`, phase 7 asks at a terminal what to review, and the rehearsal runs at one:
    found by review, each phase 7 step would have stopped there."""
    import rehearse

    for label, argv, _codes in rehearse.STEPS:
        if "phase_7_hardened.review" in argv:
            assert "--base" in argv or "--all" in argv, label


def test_the_rehearsal_expects_each_steps_own_answer(monkeypatch, capsys) -> None:
    """Measured before: the `--max-tokens 2000` step exits 3 by design — the ceiling refusing is its lesson — and
    the rehearsal counted that 3 as a failure, so a clean rehearsal always ended in exit 3."""
    import rehearse

    fixed = False

    def answered(argv, **_kwargs):
        nonlocal fixed
        fixed = fixed or "--fix" in argv  # the talk's fix moment: from here the command approves
        verdict = "-m" in argv and "phase_4_first_review.review" not in argv and not fixed  # phase 4 never exits 1
        return SimpleNamespace(returncode=3 if "--max-tokens" in argv else 1 if verdict else 0)

    monkeypatch.setattr(rehearse.subprocess, "run", answered)
    assert rehearse.main([]) == 0, capsys.readouterr().out
    labels = [label for label, _tail, _codes in rehearse.STEPS]
    assert labels[-2:] == ["the fix: make_demo_repo.py --fix", "phase 6 after the fix"], "the punchline is rehearsed"

    def crashed(_argv, **_kwargs):  # an uncaught exception is Python's exit 1, a verdict's code too
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(rehearse.subprocess, "run", crashed)
    assert rehearse.main([]) == 3, "a step that answers no verdict and exits 1 crashed"
    out = capsys.readouterr().out
    assert "- exit 1  phase 1: hello  <- not what the talk expects" in out, out

    def broke(_argv, **_kwargs):
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(rehearse.subprocess, "run", broke)
    assert rehearse.main([]) == 3, "a step that failed is still a failure"


def test_the_demo_repository_is_committed_with_lf_on_every_platform(demo_repo: Path) -> None:
    """Measured by review: written in text mode, every file of the demo repository took `\\r\\n` on Windows, and
    git committed it so, the system's `core.autocrlf` unread: phases 2 to 5 showed the model a `\\r` a line."""
    blob = _git_in(demo_repo, "show", "feature/payments:src/payments/charge.py")
    assert "\r" not in blob and "\n" in blob


def test_a_demo_repository_windows_holds_open_is_a_sentence(tmp_path: Path, monkeypatch, capsys) -> None:
    """Windows deletes no folder a terminal or an editor holds open. Measured by review: the rebuild ended in a
    traceback, the repository half removed."""
    import make_demo_repo as module

    (tmp_path / "demo").mkdir()

    def held(_path, **_kwargs):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(module.shutil, "rmtree", held)
    assert module.main([str(tmp_path / "demo")]) == 1
    err = capsys.readouterr().err
    assert "close what holds it open" in err and "Traceback" not in err, err


def test_a_step_that_hangs_is_stopped_named_and_the_next_still_runs(monkeypatch, capsys) -> None:
    """Phases 4 and 5 set no request deadline. Measured by review: one hung call stalled the whole rehearsal,
    though its docstring says the next step still runs."""
    import subprocess

    import rehearse

    def hung(argv, **kwargs):
        if "phase_5_parallel_lanes.review" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rehearse.subprocess, "run", hung)
    assert rehearse.main([]) == 3
    out = capsys.readouterr().out
    assert f"- timed out after {rehearse.STEP_TIMEOUT_S} s  phase 5: parallel lanes  <- not what" in out, out
    assert "- exit 0  phase 6: the command" in out, "the next step still ran"


def test_the_fix_run_twice_is_the_fix_once_and_before_a_build_is_a_sentence(tmp_path: Path, capsys) -> None:
    """The talk's fix moment. Measured by review: a second `--fix`, as a rehearsal and then the talk run it, ended
    in a traceback, `git commit` finding nothing to commit; and `--fix` before the build ended in one from `git
    checkout`."""
    import make_demo_repo

    root = tmp_path / "demo"
    assert make_demo_repo.main([str(root), "--fix"]) == 1
    assert "build it first" in capsys.readouterr().err
    assert make_demo_repo.main([str(root)]) == 0
    assert make_demo_repo.main([str(root), "--fix"]) == 0
    assert make_demo_repo.main([str(root), "--fix"]) == 0
    assert "fixed already" in capsys.readouterr().out


def test_the_copilot_login_says_how_to_use_it_and_logs_in_to_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    """Measured by review: with no token cached, `copilot_login.py --help` began a real device login, the trap the
    demo script's parser was built to close."""
    import copilot_login

    monkeypatch.setattr(copilot_login, "token_path", lambda: tmp_path / "none")
    with pytest.raises(SystemExit) as stopped:
        copilot_login.main(["--help"])
    assert stopped.value.code == 0 and "--force" in capsys.readouterr().out


#: A report as phase 7 prints it, trimmed: a gate's finding, a lane's kept and folded ones, a failed lane.
MEASURED = """### gate_secrets
- **blocker** hard-coded credential (aws_access_key_id) (src/payments/config.py:4)
### lane_security
- **blocker** Shell injection vulnerability via unsanitized printer name (src/payments/charge.py:27)
- folded into `gate_secrets`'s finding on the same lines: Sensitive credentials in source (src/payments/config.py:4)
### lane_tests
- **major** No tests for daily_total function (src/payments/report.py:8)
### lane_complexity — FAILED: RESOURCE_EXHAUSTED: 429
- findings dropped for evidence not in the diff: 2
- spend: 3 model call(s) completed of 3 attempted, 4,678 tokens"""


def test_the_measurement_reads_a_report_as_a_person_would() -> None:
    """A lane named the shell call and, folded into the gate's, the key pair; the gate's own finding is no lane's;
    `report.py:8` is `daily_total`, not the copied block at lines 4 and 5."""
    import measure

    assert measure.read(MEASURED) == ({"shell call", "key pair"}, 2, 4678)


def _measured_runs(monkeypatch, measure) -> list[list[str]]:
    """Every command `measure` runs, answered without running it: each review exits 1 with `MEASURED`, the rest
    name a commit."""
    commands = []

    def ran(argv, **_kwargs):
        commands.append(argv)
        reviewed = "-m" in argv
        return SimpleNamespace(returncode=1 if reviewed else 0, stdout=MEASURED if reviewed else "c0ffee1\n")

    monkeypatch.setattr(measure.subprocess, "run", ran)
    return commands


def test_the_measurement_counts_each_planted_defect_across_runs(monkeypatch, capsys) -> None:
    import measure

    _measured_runs(monkeypatch, measure)
    assert measure.main(["--runs", "2"]) == 0
    out = capsys.readouterr().out
    assert "phase 7 at c0ffee1, 2 runs of the planted branch" in out
    assert "- shell call: named by a lane in 2 of 2" in out and "- copied block: named by a lane in 0 of 2" in out
    assert "- exit 1, the verdict the planted blockers call for: 2 of 2" in out
    assert "- a run: 4,678 tokens" in out


def test_the_measurement_reviews_the_planted_branch_as_a_whole_project_on_request(monkeypatch, capsys) -> None:
    """`--all` is phase 7's, so the measurement passes it on and says so; phase 6 has no whole project to review."""
    import measure

    commands = _measured_runs(monkeypatch, measure)
    assert measure.main(["--runs", "1", "--all"]) == 0
    assert [argv[-1] for argv in commands if "-m" in argv] == ["--all"]
    assert "phase 7 at c0ffee1, 1 runs of the planted branch as a whole project" in capsys.readouterr().out
    with pytest.raises(SystemExit) as refused:
        measure.main(["--all", "--phase", "6"])
    assert refused.value.code == 2
