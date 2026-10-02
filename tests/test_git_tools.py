"""The git tools, against a real repository: every answer is an envelope, and a wrong branch is a sentence."""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import (
    BASE,
    FORGING,
    HEAD,
    HIDDEN,
    KEY_LINE,
    ROOT,
    UNKNOWN_USER_REPO,
    UNRELATED,
    _git_in,
    missing_objects,
    run_review,
    tool_context,
)

from phase_2_preflight.tools import inspect_repository
from phase_3_changed_files import tools

#: Where each phase keeps its git, and where the tools a model calls live.
GIT = {
    "phase_2_preflight": ("phase_2_preflight.tools", "phase_2_preflight.tools"),
    "phase_3_changed_files": ("phase_3_changed_files.tools", "phase_3_changed_files.tools"),
    "phase_4_first_review": ("phase_4_first_review.tools", "phase_4_first_review.tools"),
    "phase_5_parallel_lanes": ("phase_5_parallel_lanes.tools", "phase_5_parallel_lanes.tools"),
    "phase_6_reviewer": ("phase_6_reviewer.tools", "phase_6_reviewer.tools"),
    "phase_7_hardened": ("phase_7_hardened.collect.git", "phase_7_hardened.judge.tools"),
}
#: The phases with a command: `review.py` exists from phase 4 on.
COMMANDS = [phase for phase in sorted(GIT) if (ROOT / phase / "review.py").is_file()]
#: The commands whose code reads every diff before any model does, so a diff git could not read is theirs to name.
READ_IN_CODE = ["phase_6_reviewer", "phase_7_hardened"]
#: The phases whose tools list a change and show its diffs: from phase 3 on.
DIFFING = [phase for phase in sorted(GIT) if phase != "phase_2_preflight"]
#: No git call can finish in a microsecond: this is a real timeout, the process started and killed.
NO_TIME = 1e-6


def _listed_and_shown(module, repo: Path, head: str, path: str) -> tuple[list[dict], str]:
    """What the chat tools list on `head`, and `path`'s diff as they show it, called in the order a model is told."""
    context = tool_context()
    module.inspect_repository(str(repo), BASE, head, context)
    return module.changed_files(context)["files"], module.show_diff(path, context)["diff"]


def _twenty_lines(root: Path) -> Path:
    """`main` holding a twenty-line `pay.py`, and `change` adding one line in its middle: three lines of context
    either side, as git prints a diff for no one's settings."""
    repo = root / "repo"
    repo.mkdir()
    _git_in(repo, "init", "-q", "-b", BASE)
    (repo / "pay.py").write_text("".join(f"line_{n} = {n}\n" for n in range(20)), encoding="utf-8", newline="\n")
    _git_in(repo, "add", "pay.py")
    _git_in(repo, "commit", "-q", "-m", "base")
    _git_in(repo, "checkout", "-q", "-b", "change")
    text = (repo / "pay.py").read_text(encoding="utf-8").replace("line_10 = 10\n", "line_10 = 10\nadded = 1\n")
    (repo / "pay.py").write_text(text, encoding="utf-8", newline="\n")
    _git_in(repo, "commit", "-q", "-am", "one line")
    return repo


#: A person's own git settings that each changed what the review read, measured before: no context lines, no `a/`
#: and `b/` in the header, or every Python file read as binary, so the gates saw no added line at all.
THEIR_SETTINGS = {
    "GIT_DIFF_OPTS=-u0 in the shell": lambda _repo, _home, env: env.setenv("GIT_DIFF_OPTS", "-u0"),
    "diff.context=0 in their global config": lambda _repo, home, _env: (home / ".gitconfig").write_text(
        "[diff]\n\tcontext = 0\n\tnoprefix = true\n", encoding="utf-8"
    ),
    "*.py -diff in their attributes file": lambda _repo, home, _env: (
        (home / ".config" / "git").mkdir(parents=True),
        (home / ".config" / "git" / "attributes").write_text("*.py -diff\n", encoding="utf-8"),
    ),
    "diff.context=0 in the repository's own config": lambda repo, _home, _env: (
        _git_in(repo, "config", "diff.context", "0"),
        _git_in(repo, "config", "diff.noprefix", "true"),
    ),
}


class TestNoOnesSettings:
    """What git prints for a review is git's default, whoever runs it: every inherited `GIT_*` variable left out, no
    global or system config, no attributes but the repository's, and the diff read through plumbing, which no
    display setting of the repository's own reaches."""

    @pytest.mark.parametrize("setting", THEIR_SETTINGS)
    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_diff_reads_the_same_whatever_their_settings(
        self, phase: str, setting: str, tmp_path: Path, monkeypatch
    ) -> None:
        repo, home = _twenty_lines(tmp_path), tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        THEIR_SETTINGS[setting](repo, home, monkeypatch)
        _files, diff = _listed_and_shown(importlib.import_module(GIT[phase][1]), repo, "change", "pay.py")
        assert diff.startswith("diff --git a/pay.py b/pay.py") and "Binary files" not in diff, diff
        assert sum(line.startswith(" ") for line in diff.splitlines()) == 6, diff

    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_variable_naming_another_repositorys_refs_is_never_inherited(
        self, phase: str, tmp_path: Path, demo_repo: Path, monkeypatch
    ) -> None:
        """git 2.54's `GIT_REFERENCE_BACKEND` outranks the repository's own config: measured, it answered another
        repository's commit for `main`. A list of variables to leave out missed it; leaving out every `GIT_*` does
        not."""
        repo = _twenty_lines(tmp_path)
        ours = _git_in(repo, "rev-parse", BASE)  # before the variable: the test's own git inherits it too
        monkeypatch.setenv("GIT_REFERENCE_BACKEND", f"files://{demo_repo}/.git")
        context = tool_context()
        out = importlib.import_module(GIT[phase][1]).inspect_repository(str(repo), BASE, "change", context)
        assert out["status"] == "success" and out["base_sha"] == ours, out


@pytest.mark.parametrize("phase", sorted(GIT))
def test_a_tools_docstring_speaks_to_the_model_in_words(phase: str) -> None:
    """ADK sends a tool's docstring to the model as it is written. Measured by review: `show_diff` told the model its
    diff was "capped at DIFF_CAP_CHARS", a name only the code knows; the cap is a number the model can use."""
    import re

    model_tools, git = importlib.import_module(GIT[phase][1]), importlib.import_module(GIT[phase][0])
    for name in ("inspect_repository", "changed_files", "show_diff"):
        doc = getattr(getattr(model_tools, name, None), "__doc__", None) or ""
        assert not re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", doc), (name, doc[:120])
    if hasattr(model_tools, "show_diff"):
        assert f"{git.DIFF_CAP_CHARS:,} characters" in model_tools.show_diff.__doc__


class TestInspectRepository:
    def test_a_real_branch_pair_is_described_with_its_shas(self, demo_repo: Path) -> None:
        out = inspect_repository(str(demo_repo), BASE, HEAD)
        assert out["status"] == "success", out
        assert len(out["base_sha"]) == 40 and len(out["head_sha"]) == 40
        assert out["merge_base"] == out["base_sha"], "the feature branch sits directly on main"
        assert out["commits_ahead"] == 1

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_a_missing_branch_is_an_error_envelope_not_an_exception(self, phase: str, demo_repo: Path) -> None:
        """The commonest typo, in every phase. Measured by coverage: phases 6 and 7 answered it in no test."""
        model_tools = importlib.import_module(GIT[phase][1])
        context = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(demo_repo), "main", "feature/does-not-exist", *context)
        assert out["status"] == "error" and "feature/does-not-exist" in out["error_message"], out

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_a_directory_that_is_not_a_repository_is_named(self, phase: str, tmp_path: Path) -> None:
        model_tools = importlib.import_module(GIT[phase][1])
        context = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(tmp_path), "main", "main", *context)
        assert out["status"] == "error" and "not a git repository" in out["error_message"], out

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_a_home_of_a_user_this_machine_does_not_know_is_an_error_envelope(self, phase: str) -> None:
        """`~name` for a user that does not exist is left as typed, so the repository check answers; `Path.expanduser`
        raised here once, and a tool never raises at the model."""
        model_tools = importlib.import_module(GIT[phase][1])
        context = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(UNKNOWN_USER_REPO, "main", "main", *context)
        assert out["status"] == "error" and UNKNOWN_USER_REPO in out["error_message"], out

    def test_a_branch_name_that_looks_like_an_option_is_still_a_branch(self, demo_repo: Path) -> None:
        """`--verify --quiet` would read `-x` as a flag; the separator makes it a ref, and a missing one."""
        out = inspect_repository(str(demo_repo), "main", "-x")
        assert out["status"] == "error" and "'-x'" in out["error_message"]


class TestTheScopeLivesInState:
    """From phase 3 on, one tool's answer is the next tool's boundary: `inspect_repository` leaves the scope it
    confirmed in session state, `changed_files` and `show_diff` read it and take no repository at all. Measured in
    chat mode before this: every tool resolved the repository again, twenty-nine git processes where nine would do."""

    def test_the_tools_after_the_preflight_read_it_from_state(self, demo_repo: Path) -> None:
        context = tool_context()
        assert tools.inspect_repository(str(demo_repo), BASE, HEAD, context)["status"] == "success"
        assert context.state["review_scope"]["merge_base"]
        out = tools.changed_files(context)
        assert out["status"] == "success", out
        assert {(f["path"], f["status"]) for f in out["files"]} == {
            ("src/payments/charge.py", "M"),
            ("src/payments/config.py", "A"),
            ("src/payments/refund.py", "A"),
            ("src/payments/report.py", "A"),
        }
        assert list(context.state["review_files"]) == sorted(f["path"] for f in out["files"]), "show_diff's allowlist"
        diff = tools.show_diff("src/payments/charge.py", context)
        assert diff["status"] == "success" and "shell=True" in diff["diff"] and diff["cut"] is False

    @pytest.mark.parametrize("phase", ["phase_3_changed_files", "phase_6_reviewer"])
    def test_the_repository_is_resolved_once_for_the_whole_conversation(
        self, demo_repo: Path, phase: str, monkeypatch
    ) -> None:
        module = importlib.import_module(f"{phase}.tools")
        calls: list[tuple] = []
        real = module._preflight
        monkeypatch.setattr(module, "_preflight", lambda *a: (calls.append(a), real(*a))[1])
        context = tool_context()
        module.inspect_repository(str(demo_repo), BASE, HEAD, context)
        module.changed_files(context)
        module.show_diff("src/payments/charge.py", context)
        module.show_diff("src/payments/config.py", context)
        assert len(calls) == 1, "resolved once; nothing after it resolves again"

    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_renamed_file_is_read_as_the_lines_it_moved_and_changed(self, phase: str, hostile_repo: Path) -> None:
        """Measured before: `show_diff` read a rename by its new path alone, so a renamed file with one change read
        as every line added, the change among them unmarked."""
        module = importlib.import_module(GIT[phase][1])
        files, diff = _listed_and_shown(module, hostile_repo, "renamed", "money_rates.py")
        assert files == [{"path": "money_rates.py", "status": "R", "old": "rates.py"}]
        assert "rename from rates.py" in diff and "new file mode" not in diff, diff[:400]
        assert [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")] == [
            "+added = 1"
        ]

    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_rename_reads_its_own_pair_even_where_its_old_name_is_now_a_folder(
        self, phase: str, hostile_repo: Path
    ) -> None:
        """Measured before: `a` renamed to `b.py` beside a new `a/x.py` holding a key, and `-- a b.py` matched
        everything under `a/` too, so `b.py`'s diff carried `a/x.py`'s key, a finding at a line `b.py` never had."""
        _files, diff = _listed_and_shown(importlib.import_module(GIT[phase][1]), hostile_repo, "folded", "notes.txt")
        assert "rename from notes.md" in diff and "notes.md/x.py" not in diff and "AKIA" not in diff, diff
        if phase in READ_IN_CODE:
            evidence = importlib.import_module(GIT[phase][0]).collect_evidence(str(hostile_repo), BASE, "folded")
            moved = next(f for f in evidence["files"] if f["path"] == "notes.txt")
            assert "notes.md/x.py" not in moved["diff"] and moved["added"] == [], moved

    @pytest.mark.parametrize("variable", ["GIT_LITERAL_PATHSPECS", "GIT_ICASE_PATHSPECS", "GIT_GLOB_PATHSPECS"])
    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_path_is_read_as_itself_whatever_the_shell_says_of_pathspecs(
        self, phase: str, variable: str, hostile_repo: Path, monkeypatch
    ) -> None:
        """git reads four variables that change what a path means; the reviewer's own run is the one it asked for.
        Measured before: `GIT_ICASE_PATHSPECS=1` gave `a.py`'s diff `A.py`'s lines too."""
        monkeypatch.setenv(variable, "1")
        _files, diff = _listed_and_shown(importlib.import_module(GIT[phase][1]), hostile_repo, "twins", "t.py")
        assert "+lower = 1" in diff and "AKIA" not in diff, diff

    @pytest.mark.parametrize("phase", DIFFING)
    def test_a_backslash_in_a_name_is_part_of_the_name(self, phase: str, hostile_repo: Path) -> None:
        """Git for Windows reads `\\` in a pathspec as a folder's separator unless the path is from the top: a branch
        made elsewhere with `cfg\\keys.py` beside `cfg/keys.py` had the second's diff shown for the first, and the key
        in the first read by no gate and no lane."""
        tools_of = importlib.import_module(GIT[phase][1])
        _files, diff = _listed_and_shown(tools_of, hostile_repo, "backslash", "cfg\\keys.py")
        assert "AKIA" in diff and "slash = 1" not in diff, diff
        specs = importlib.import_module(GIT[phase][0])._literally("cfg\\keys.py")
        assert all(spec.startswith(":(top,") for spec in specs), "from the top, git leaves a path as spelled"

    def test_before_the_preflight_the_later_tools_say_what_to_call(self) -> None:
        context = tool_context()
        assert "inspect_repository first" in tools.changed_files(context)["error_message"]
        assert "inspect_repository first" in tools.show_diff("src/a.py", context)["error_message"]

    def test_a_failed_preflight_clears_the_scope(self, demo_repo: Path) -> None:
        context = tool_context()
        tools.inspect_repository(str(demo_repo), BASE, HEAD, context)
        tools.changed_files(context)
        out = tools.inspect_repository(str(demo_repo), "main", "nope", context)
        assert out["status"] == "error" and "'nope'" in out["error_message"]
        assert context.state["review_scope"] is None and context.state["review_files"] is None
        assert tools.changed_files(context)["status"] == "error", "nothing reads a repository this call did not confirm"

    def test_a_long_diff_is_cut_and_says_so(self, demo_repo: Path, monkeypatch) -> None:
        """A cut the model cannot see is a boundary it will report on."""
        monkeypatch.setattr(tools, "DIFF_CAP_CHARS", 80)
        context = tool_context()
        tools.inspect_repository(str(demo_repo), BASE, HEAD, context)
        out = tools.show_diff("src/payments/charge.py", context)
        assert out["cut"] is True and "[… cut at 80 characters]" in out["diff"]
        assert len(out["diff"]) < 80 + 40


class TestGitPastItsTimeout:
    """Every git call carries a timeout, and a call past it is killed. Measured before this: `TimeoutExpired` rose
    through every tool, at the model, and through every command as a traceback. And several helpers read git's
    answer without its exit code, so a timeout answered as an empty one would have read as an empty change."""

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_every_tool_answers_a_timeout_with_an_envelope_naming_it(
        self, phase: str, demo_repo: Path, monkeypatch
    ) -> None:
        git, model_tools = (importlib.import_module(name) for name in GIT[phase])
        context = tool_context()
        scope = (str(demo_repo), BASE, HEAD) + (() if phase == "phase_2_preflight" else (context,))
        assert model_tools.inspect_repository(*scope)["status"] == "success"
        monkeypatch.setattr(git, "GIT_TIMEOUT_S", NO_TIME)
        answers = []
        if hasattr(model_tools, "changed_files"):  # before the preflight below, which clears the scope it fails
            answers += [model_tools.changed_files(context), model_tools.show_diff("src/payments/charge.py", context)]
        answers.append(model_tools.inspect_repository(*scope))
        assert all(a["status"] == "error" and "did not answer within" in a["error_message"] for a in answers), answers

    @pytest.mark.parametrize("phase", COMMANDS)
    def test_every_command_names_a_timeout_and_exits_2_before_any_model(
        self, phase: str, demo_repo: Path, monkeypatch, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        monkeypatch.setattr(importlib.import_module(GIT[phase][0]), "GIT_TIMEOUT_S", NO_TIME)
        assert run_review(command, demo_repo) == 2
        err = capsys.readouterr().err
        assert "did not answer within" in err and "Traceback" not in err, err

    @pytest.mark.skipif(os.name != "nt", reason="off Windows `run` never read a killed command's output to its end")
    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_a_timeout_stops_what_the_command_started_too(self, phase: str, monkeypatch) -> None:
        """Git for Windows' `git.exe` runs the real git as its child. `subprocess.run` kills the first and then, on
        Windows, reads the output to its end, which the child holds open: a git past its timeout hung the review.
        A command that starts a child holding its output stands in for it."""
        git = importlib.import_module(GIT[phase][0])
        monkeypatch.setattr(git, "GIT_TIMEOUT_S", 1)
        child = "import time; time.sleep(20)"
        parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(20)"
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            git._run([sys.executable, "-c", parent], dict(os.environ))
        assert time.monotonic() - started < 10, "waited for the child, not the timeout"

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_git_is_found_on_path_never_in_the_current_directory(self, phase: str, tmp_path, monkeypatch) -> None:
        """Windows looks for a program in the current directory before PATH, and the current directory can be the
        checkout under review: its own `git.exe` would run. Git is run by its full path, as PATH finds it."""
        git = importlib.import_module(GIT[phase][0])
        program = tmp_path / ("git.exe" if os.name == "nt" else "git")  # a program of that name, empty: never run
        program.touch()
        program.chmod(0o755)
        monkeypatch.chdir(tmp_path)
        git._found.cache_clear()  # looked up now, from here: never an answer cached before
        found = Path((getattr(git, "on_path", None) or git._on_path)("git"))  # phase 7 lends it to its lint gate
        assert found.is_absolute() and found.parent != tmp_path, found

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_git_not_on_path_is_a_named_error(self, phase: str, demo_repo: Path, tmp_path, monkeypatch) -> None:
        """Measured before: with no git on PATH — Git for Windows can be installed for Git Bash alone — every
        command ended in a traceback and exit 1, the blocker's code."""
        model_tools = importlib.import_module(GIT[phase][1])
        monkeypatch.setenv("PATH", str(tmp_path))
        scope = (str(demo_repo), BASE, HEAD) + (() if phase == "phase_2_preflight" else (tool_context(),))
        answer = model_tools.inspect_repository(*scope)
        assert answer["status"] == "error" and "git is not on PATH" in answer["error_message"], answer

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_diff_past_its_timeout_after_a_good_preflight_is_named_never_an_empty_change(
        self, phase: str, demo_repo: Path, monkeypatch
    ) -> None:
        git = importlib.import_module(GIT[phase][0])
        run = git._run

        def only_the_diff_times_out(argv, *args, **kwargs):
            if "diff-tree" in argv and "-p" in argv:  # one file's patch, never the list of changed files
                raise subprocess.TimeoutExpired(argv, NO_TIME)
            return run(argv, *args, **kwargs)

        monkeypatch.setattr(git, "_run", only_the_diff_times_out)
        out = git.collect_evidence(str(demo_repo), BASE, HEAD)
        assert out["status"] == "error" and "git diff-tree did not answer within" in out["error_message"], out


class TestGitThatFails:
    """A git call that fails is named, never read as an empty answer. Measured before this: phases 6 and 7
    approved, exit 0, a branch sharing no history with main (no merge base, so no file listed) and a partial clone
    whose origin had gone (every diff empty) — each carrying a change neither had read."""

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_every_tool_names_a_branch_sharing_no_history(self, phase: str, unrelated_repo: Path) -> None:
        model_tools = importlib.import_module(GIT[phase][1])
        scoped = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(unrelated_repo), BASE, UNRELATED, *scoped)
        assert out["status"] == "error" and "share no history" in out["error_message"], out

    @pytest.mark.parametrize("clone", ["shallow_clone", "misled_clone"])
    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_every_tool_refuses_a_shallow_clone(self, phase: str, clone: str, request) -> None:
        """Before any merge base is asked for: at depth 1 `merge-base` answers 1, as for no shared history, and in
        the misled clone it answers with the wrong commit."""
        model_tools = importlib.import_module(GIT[phase][1])
        scoped = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(request.getfixturevalue(clone)), BASE, HEAD, *scoped)
        assert out["status"] == "error" and "shallow clone" in out["error_message"], out
        assert "share no history" not in out["error_message"], out

    @pytest.mark.parametrize("clone", ["cut_off_clone", "partial_clone"])
    @pytest.mark.parametrize("phase", DIFFING)
    def test_every_tool_names_a_diff_git_could_not_read(self, phase: str, clone: str, request) -> None:
        """Without fetching what the clone lacks, its origin gone or not: nothing writes into the repository under
        review. Measured before the fix: with the origin there, the tool fetched the file and answered."""
        repo = request.getfixturevalue(clone)
        missing = missing_objects(repo)
        model_tools = importlib.import_module(GIT[phase][1])
        context = tool_context()
        assert model_tools.inspect_repository(str(repo), BASE, HEAD, context)["status"] == "success"
        assert model_tools.changed_files(context)["status"] == "success", "the list needs no file's content"
        out = model_tools.show_diff("src/payments/charge.py", context)
        assert out["status"] == "error" and out["error_message"].startswith("git diff-tree failed: "), out
        assert missing_objects(repo) == missing, "a lazy fetch wrote into the repository under review"

    @pytest.mark.parametrize("phase", COMMANDS)
    def test_every_command_names_a_branch_sharing_no_history(
        self, phase: str, unrelated_repo: Path, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(unrelated_repo), "--base", BASE, "--head", UNRELATED]) == 2
        err = capsys.readouterr().err
        assert "share no history" in err and "Traceback" not in err, err

    @pytest.mark.parametrize("phase", COMMANDS)
    def test_every_command_names_a_shallow_clone_and_how_to_deepen_it(
        self, phase: str, shallow_clone: Path, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert run_review(command, shallow_clone) == 2
        err = capsys.readouterr().err
        assert "shallow clone" in err and "git fetch --unshallow" in err and "Traceback" not in err, err

    @pytest.mark.parametrize("clone", ["cut_off_clone", "partial_clone"])
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_diff_git_could_not_read_is_named_never_approved(self, phase: str, clone: str, request, capsys) -> None:
        repo = request.getfixturevalue(clone)
        missing = missing_objects(repo)
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert run_review(command, repo) == 2
        err = capsys.readouterr().err
        assert "git diff-tree failed: " in err and "Traceback" not in err, err
        assert missing_objects(repo) == missing, "a lazy fetch wrote into the repository under review"


class TestWhatARefNames:
    """A name resolves to one commit or is refused. Measured before: a fork's tag `main`, on its own head, won over
    the branch `main` — git prefers a tag, and `rev-parse --quiet` hid its "ambiguous" warning — so the base was the
    head, and phase 7 approved, exit 0, a change it had read none of."""

    @pytest.mark.parametrize("spelling", ["twin", "twin~0", "twin^0", "a tag spelled as a short sha"])
    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_every_tool_refuses_a_name_that_means_two_things(
        self, phase: str, spelling: str, hostile_repo: Path
    ) -> None:
        """However it is spelled: before, `twin~0` named no ref and passed, and a tag named as a commit's short sha
        won over that commit, git preferring a ref to an abbreviated object without a word under `--quiet`."""
        if spelling.startswith("a tag"):
            spelling = _git_in(hostile_repo, "rev-parse", "carriage")[:7]
        model_tools = importlib.import_module(GIT[phase][1])
        scoped = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(hostile_repo), BASE, spelling, *scoped)
        assert out["status"] == "error" and f"{spelling!r} is ambiguous" in out["error_message"], out

    @pytest.mark.parametrize("phase", COMMANDS)
    def test_every_command_refuses_an_ambiguous_base(self, phase: str, hostile_repo: Path, request, capsys) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", "twin", "--head", "carriage"]) == 2
        err = capsys.readouterr().err
        assert "'twin' is ambiguous" in err and "Traceback" not in err, err

    @pytest.mark.parametrize("phase", sorted(GIT))
    def test_an_annotated_tag_names_the_commit_it_tags(self, phase: str, hostile_repo: Path) -> None:
        """Measured before: the head's sha was the tag object's, a sha no reader of the report could check out."""
        model_tools = importlib.import_module(GIT[phase][1])
        scoped = () if phase == "phase_2_preflight" else (tool_context(),)
        out = model_tools.inspect_repository(str(hostile_repo), BASE, "v1", *scoped)
        assert out["status"] == "success" and out["head_sha"] == _git_in(hostile_repo, "rev-parse", "carriage"), out

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_name_that_is_only_a_tag_is_named_as_one(self, phase: str, hostile_repo: Path, request, capsys) -> None:
        """Git resolves a name that is only a tag to it, as it must for `--base v1.0`, so a fork's tag `origin/main`,
        with no such branch fetched, stood in for the branch unseen: the report now says which tag it read."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        command.main([str(hostile_repo), "--base", "release/base", "--head", "carriage"])
        header = [line for line in capsys.readouterr().out.splitlines() if line.startswith("- against")]
        assert header and "release/base (the tag refs/tags/release/base) @ " in header[0], header


@pytest.fixture
def reviewers_git_config(tmp_path: Path, monkeypatch) -> None:
    """The reviewer's own global git config, as a diff tool or a terminal setup leaves it: colour always on, and an
    external diff (`cat` here: any command that prints something other than a unified diff)."""
    config = tmp_path / "gitconfig"
    settings = "[color]\n\tui = always\n[diff]\n\texternal = cat\n\tsuppressBlankEmpty = true\n"
    config.write_text(settings, encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


class TestWhatABranchCannotHide:
    """Every file's diff is read as git prints it for no one's settings. Measured before, each APPROVED, exit 0, with
    the planted key unread: a path git took as pathspec magic (`:config.py`, an empty diff), the branch's own
    `.gitattributes` marking the key's file `-diff` ("Binary files differ"), and the reviewer's `color.ui=always` or
    `diff.external`, whose output no hunk header could be read from."""

    @pytest.mark.parametrize("branch", ["pathspec", "attributes", "nfd"])
    @pytest.mark.parametrize("phase", DIFFING)
    def test_every_tool_shows_the_lines_the_branch_hid(self, phase: str, branch: str, hostile_repo: Path) -> None:
        module = importlib.import_module(GIT[phase][1])
        _files, diff = _listed_and_shown(module, hostile_repo, branch, HIDDEN[branch])
        assert f"+{KEY_LINE.strip()}" in diff, diff

    @pytest.mark.usefixtures("reviewers_git_config")
    @pytest.mark.parametrize("phase", DIFFING)
    def test_every_tool_reads_past_the_reviewers_git_config(self, phase: str, demo_repo: Path) -> None:
        module = importlib.import_module(GIT[phase][1])
        _files, diff = _listed_and_shown(module, demo_repo, HEAD, "src/payments/charge.py")
        assert diff.startswith("diff --git") and "\n@@ " in diff and "\x1b[" not in diff, diff

    @pytest.mark.parametrize("branch", list(HIDDEN))
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_key_the_branch_hid_is_found_where_it_is_and_blocks(
        self, phase: str, branch: str, hostile_repo: Path, request, capsys
    ) -> None:
        """A lone carriage return too: before, it split one line of the file in two, and the key after it was no
        added line, so the gate never read it."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", branch]) == 1
        out = capsys.readouterr().out
        assert "hard-coded credential" in out and f"({HIDDEN[branch]}:1)" in out, out

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_the_lanes_read_no_line_break_but_newline(self, phase: str, hostile_repo: Path) -> None:
        """A form feed, a lone `\\r` or U+2028 starts a line for a reader and for `str.splitlines`, with no diff
        marker: the key hid behind one, and text after one read as the prompt's own. Each is shown as its escape."""
        git = importlib.import_module(GIT[phase][0])
        evidence = git.collect_evidence(str(hostile_repo), BASE, "carriage")
        assert evidence["diff"].splitlines() == evidence["diff"].split("\n"), "a line break the lanes would see"
        assert '+REGION = "eu"\\rAWS_ACCESS_KEY_ID' in evidence["diff"], "the escape, on the line it was on"

    @pytest.mark.usefixtures("reviewers_git_config")
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_the_reviewers_git_config_moves_no_line(self, phase: str, hostile_repo: Path, request, capsys) -> None:
        """`diff.suppressBlankEmpty` prints a blank context line as nothing at all: measured before, the gate put the
        key a line early, at `settings.py:3`."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", "blank"]) == 1
        assert "(settings.py:4)" in capsys.readouterr().out

    @pytest.mark.usefixtures("reviewers_git_config")
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_the_reviewers_git_config_hides_nothing(self, phase: str, demo_repo: Path, request, capsys) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert run_review(command, demo_repo) == 1
        assert "hard-coded credential" in capsys.readouterr().out


class TestWhatNoLaneCouldRead:
    """A change of which no line reached the lanes, or only its start, is named and never approved. Measured before,
    each APPROVED, exit 0: a branch changing nothing, a binary file, and a file whose defect sat past the diff cap."""

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_branch_that_changes_nothing_is_no_change_to_review(
        self, phase: str, hostile_repo: Path, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", "empty"]) == 2
        err = capsys.readouterr().err
        assert "no change to review" in err and "Traceback" not in err, err

    @pytest.mark.parametrize(
        ("branch", "path", "why"), [("binary", "logo.png", "binary"), ("long", "pay.py", "cut at")]
    )
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_file_the_lanes_could_not_read_whole_is_named_and_degrades(
        self, phase: str, branch: str, path: str, why: str, hostile_repo: Path, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", branch]) == 3
        out = capsys.readouterr().out
        assert "## Verdict: DEGRADED" in out, out
        named = [line for line in out.splitlines() if line.startswith("- not read") and f"`{path}`" in line]
        assert named and why in named[0], out


@pytest.fixture(params=["replace", "graft"])
def rewritten_repo(request, tmp_path: Path) -> Path:
    """A branch adding the key, in a repository whose history git reads rewritten: a replace ref swapping the key's
    file for a harmless one, or a graft making the key's commit an ancestor of `main`. Measured before: the first
    APPROVED, exit 0, the second reviewed no change at all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_in(repo, "init", "-q", "-b", BASE)
    _git_in(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git_in(repo, "checkout", "-q", "-b", HEAD)
    (repo / "config.py").write_text(KEY_LINE, encoding="utf-8", newline="\n")
    _git_in(repo, "add", ".")
    _git_in(repo, "commit", "-qm", "the key")
    _git_in(repo, "checkout", "-q", BASE)
    _git_in(repo, "commit", "-q", "--allow-empty", "-m", "main moves on")
    if request.param == "replace":
        harmless = _git_in(repo, "hash-object", "-w", "--stdin", stdin="REGION = 'eu'\n")
        _git_in(repo, "replace", _git_in(repo, "rev-parse", f"{HEAD}:config.py"), harmless)
    else:
        main, parent, key = (_git_in(repo, "rev-parse", ref) for ref in (BASE, f"{BASE}~1", HEAD))
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "grafts").write_text(f"{main} {parent} {key}\n", encoding="utf-8")
    return repo


class TestWhereGitLooks:
    """git reads the repository named, and its history as committed. Measured before: `GIT_DIR` in the environment,
    as a shell or a hook can leave it, reviewed another repository under the requested path's name; a replace ref
    and a graft each rewrote what git read."""

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_history_rewritten_where_git_reads_it_hides_nothing(
        self, phase: str, rewritten_repo: Path, request, capsys
    ) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert run_review(command, rewritten_repo) == 1
        assert "hard-coded credential" in capsys.readouterr().out

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_git_dir_in_the_environment_points_nowhere_else(
        self, phase: str, demo_repo: Path, tmp_path: Path, monkeypatch, request, capsys
    ) -> None:
        from make_demo_repo import build, fix

        fixed = build(tmp_path / "fixed")
        fix(fixed)
        monkeypatch.setenv("GIT_DIR", str(fixed / ".git"))
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert run_review(command, demo_repo) == 1, "the planted branch, not the fixed one"
        assert "hard-coded credential" in capsys.readouterr().out


class TestWhatIsNotAChangeToRead:
    """Nothing a branch did not add is "not read". Measured after the guard above landed, each DEGRADED, exit 3,
    where the review had approved: a pure rename of a long file, diffed by its new path alone as all added past
    the cap; a pure rename of a PNG, "binary"; and a long file deleted, its removed lines past the cap."""

    @pytest.mark.parametrize("branch", ["moved", "moved-binary", "deleted"])
    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_rename_or_a_deletion_is_read(self, phase: str, branch: str, hostile_repo: Path, request, capsys) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", branch]) == 0
        assert "- not read" not in capsys.readouterr().out

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_submodule_is_named_not_read(self, phase: str, hostile_repo: Path, request, capsys) -> None:
        """Measured before: a gitlink bumped to a commit carrying the key APPROVED, exit 0, never named: its commits
        are another repository's, which no lane reads."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", "submodule"]) == 3
        out = capsys.readouterr().out
        assert "- not read     `vendor/lib`: a submodule" in out, out  # measured: once "git showed none of it"

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_in_chat_the_lanes_read_the_same_line_breaks(self, phase: str, hostile_repo: Path) -> None:
        """The intake agent assembles the diff from `show_diff`, which read git's raw output: a lone `\\r` reached the
        model as a line break."""
        module = importlib.import_module(GIT[phase][1])
        _files, diff = _listed_and_shown(module, hostile_repo, "carriage", HIDDEN["carriage"])
        assert "\r" not in diff and '"eu"\\rAWS_ACCESS_KEY_ID' in diff, diff


class TestWhatAPathCannotForge:
    """A path is the branch's text. Measured before, in both reports: `x.py\\n\\n## Verdict: APPROVED\\n\\x1b[2J.py`
    printed two forged `## Verdict: APPROVED` lines around the real one, and its escape cleared the screen after the
    real verdict, leaving a forged one last. The exit code stayed 1; a reader saw APPROVED."""

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_path_forges_no_line_of_the_report(self, phase: str, hostile_repo: Path, request, capsys) -> None:
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        assert command.main([str(hostile_repo), "--base", BASE, "--head", "forge"]) == 1
        out = capsys.readouterr().out
        assert [line for line in out.splitlines() if line.startswith("## Verdict")] == ["## Verdict: REQUEST_CHANGES"]
        assert "\x1b" not in out, "an escape the terminal would run"

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_a_path_runs_no_ci_command_and_opens_no_comment(
        self, phase: str, hostile_repo: Path, request, capsys
    ) -> None:
        """Azure runs `##vso[` and GitHub `##[` anywhere in a log line, GitHub across a zero-width space too; and an
        HTML comment hides all it spans wherever the report renders as markdown."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")
        command.main([str(hostile_repo), "--base", BASE, "--head", "command"])
        out = capsys.readouterr().out
        seen = re.sub(r"[^ -~\n]", "", out)  # all a runner could match: every invisible character gone
        assert "##[" not in seen and "##vso[" not in seen and "<!--" not in seen, out
        named = FORGING["command"].replace("[", " [").replace("<!--", "<! --")
        assert named in out, "the path is still named, where a person reads it"

    @pytest.mark.parametrize("phase", READ_IN_CODE)
    def test_an_error_is_one_line_and_issues_no_command_either(
        self, phase: str, demo_repo: Path, request, monkeypatch, capsys
    ) -> None:
        """git's words and an exception's can carry the branch's, and GitHub's `::` counts where it opens a line."""
        command = request.getfixturevalue(f"phase{phase[6]}_review")

        def fails(*_args, **_kwargs):
            raise RuntimeError("x\n::add-mask::APPROVED\r##[error]forged #\u200b#vso[task.prependpath]y")

        monkeypatch.setattr(command, "collect_evidence", fails)
        assert command.main([str(demo_repo), "--base", BASE, "--head", HEAD]) == 3
        err = capsys.readouterr().err
        lines = [re.sub(r"[^ -~]", "", line) for line in re.split(r"\r\n?|\n", err) if line]
        assert lines == [
            "review: the review did not finish: RuntimeError: x ::add-mask::APPROVED ## [error]forged "
            "##vso [task.prependpath]y"
        ], err
