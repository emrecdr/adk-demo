"""Read-only git, as function tools.

ADK builds a tool's schema from the function signature and its docstring, so
the docstring is prompt material: it tells the model when to call the tool and
what comes back. Every tool returns a `{"status": ...}` dict and never raises
at the model — an exception would end the turn, an envelope lets the model
explain. Git runs as an argv list with a timeout, never through a shell, and
only with verbs that read. A parameter named `tool_context` is filled in by
ADK, never by the model: it is how a tool reaches session state — where
`inspect_repository` leaves the scope it confirmed, so the tools after it
take no repository at all.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

GIT_TIMEOUT_S = 30
#: Every string the model reads is capped in characters, and the cut is named.
DIFF_CAP_CHARS = 4_000


class GitError(Exception):
    """git could not answer: a reason to name, never an empty answer to read."""


#: What a glob pathspec reads as a pattern, each escaped where a path is only a name.
_GLOB = re.compile(r"[*?[\\]")
#: Settings that change what git prints or what it reads, fixed for every call: set through the environment, they
#: outrank every config file, the repository's own included. No attributes file but the repository's.
_SETTLED = {"core.precomposeUnicode": "false", "diff.suppressBlankEmpty": "false", "core.attributesFile": os.devnull}


def _environment(repo: str) -> dict[str, str]:
    """git's environment for a review: the caller's with every `GIT_*` variable left out, as git's own test suite
    leaves them out, and then only what a review needs: no config but the repository's own and what is fixed here,
    no attributes but the repository's, nothing fetched (a partial clone would fetch what it lacks, into the
    repository), no object replaced, no graft.

    Measured, each before: `GIT_DIR` reviewed another repository under the requested path's name, and git 2.54's
    `GIT_REFERENCE_BACKEND`, which a list of such variables had missed, read another repository's refs;
    `GIT_DIFF_OPTS=-u0` in a shell, or `diff.context=0` in a person's own config, took every context line out of a
    diff, and `*.py -diff` in their attributes file made every Python file binary; a replace ref swapped the key's
    file for a harmless one; macOS's precomposed names found no file committed in NFD; and `suppressBlankEmpty` put
    the key a line early. With a person's own config unread, so is their list of safe directories: the repository
    the operator named is the one this review trusts, as git's command-line scope allows since 2.38.
    """
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env |= {"GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1"}
    settled = _SETTLED | {"safe.directory": Path(os.path.realpath(repo)).as_posix()}
    env["GIT_CONFIG_COUNT"] = str(len(settled))
    for index, (key, value) in enumerate(settled.items()):
        env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
    return env


def _on_path(name: str) -> str:
    """`name` by its full path, as PATH finds it, never from the current directory: Windows looks there first, and
    the current directory can be the checkout under review, whose own `git.exe` must never run. Not found, the name
    alone, which is never launched: Windows would look for a bare name in the current directory too."""
    return _found(name, os.environ.get("PATH", ""))


@functools.cache
def _found(name: str, path: str) -> str:
    """Once per PATH: on Windows each lookup tries every PATHEXT."""
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"  # read by `shutil.which` on Windows, ignored elsewhere
    return shutil.which(name, path=path) or name


def _run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    """One command, bytes out, stopped whole past `GIT_TIMEOUT_S`. Git for Windows' `git.exe` runs the real git as
    its child, which holds the output open; `subprocess.run` kills only the first and then, on Windows, reads the
    output to its end, so a git past its timeout hung the review. There the whole tree is stopped first."""
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as process:
        try:
            out, err = process.communicate(timeout=GIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            if os.name == "nt":  # the tree, then the output to its end, which Windows reads on threads
                taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                subprocess.run([taskkill, "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
                process.communicate()
            process.kill()
            raise
    return subprocess.CompletedProcess(argv, process.returncode, out, err)


def _git(repo: str, *args: str, ok: tuple[int, ...] = (0,)) -> tuple[int, str]:
    """One read-only git command: an argv list, no shell, a timeout, no fetch, stdout captured, decoded as UTF-8.

    An exit code outside `ok` raises `GitError` with git's own first line, and so does a call past the timeout,
    killed, naming the limit, for the tool to answer as an envelope: some answers below are read without
    their exit code, and a failure read as an empty answer would read as nothing there. `ok` names the codes a
    caller reads as an answer: 1 is `rev-parse`'s for a ref that does not exist.
    """
    if (git := _on_path("git")) == "git":  # not on PATH: Git for Windows can be installed for Git Bash alone
        raise GitError(f"git {_verb(args)} could not start: git is not on PATH")
    try:
        done = _run([git, "-C", repo, *args], _environment(repo))
    except subprocess.TimeoutExpired:
        raise GitError(f"git {_verb(args)} did not answer within {GIT_TIMEOUT_S} s") from None
    except OSError as exc:  # found, and still could not start: no permission to run it, say
        raise GitError(f"git {_verb(args)} could not start: {exc.strerror or exc}") from None
    if done.returncode not in ok:
        said = done.stderr.decode("utf-8", "replace")
        # git's advice (`hint: ...`) comes before the error at times, and is never the reason.
        lines = [line.strip() for line in said.splitlines() if line.strip() and not line.startswith("hint:")]
        why = lines[0] if lines else f"exit {done.returncode}"
        raise GitError(f"git {_verb(args)} failed: {why}")
    # Decoded here, never in text mode, which reads a lone `\r` inside a line of a file as a line break.
    return done.returncode, done.stdout.decode("utf-8", "replace").strip()


def _verb(args: tuple[str, ...]) -> str:
    """The git command a call runs, past git's own options before it (`--attr-source`): what an error names."""
    return next((arg for arg in args if not arg.startswith("-")), "")


def _sha(repo: str, ref: str) -> str | None:
    """The commit a ref names, or None. `--end-of-options` is the one place a user
    string reaches git as an argument: a ref spelled `-x` must be a ref, never a flag. `^{commit}` names the commit
    an annotated tag tags, never the tag itself."""
    code, out = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}", ok=(0, 1))
    return out if code == 0 else None


def _namesakes(repo: str, ref: str) -> list[str]:
    """Every full ref a name could mean, however it is spelled after (`main~0` still names `main`), and, when one has
    the name and it is hex, every object it abbreviates. Git prefers a tag to a branch, and a ref to an abbreviated
    object, and `--quiet` hides its warning: a fork's tag once made the base the head. More than one is refused,
    never resolved."""
    name = ref
    for suffix in ("~", "^", ":", "@{"):
        name = name.partition(suffix)[0]
    means = [
        f"refs/{name}",
        f"refs/tags/{name}",
        f"refs/heads/{name}",
        f"refs/remotes/{name}",
        f"refs/remotes/{name}/HEAD",
    ]
    _, out = _git(repo, "for-each-ref", "--format=%(refname)", *means)
    found = [full for full in out.splitlines() if full in means]
    if found and 4 <= len(name) <= 40 and all(c in "0123456789abcdef" for c in name):
        _, objects = _git(repo, "rev-parse", f"--disambiguate={name}")  # a tag named as a short sha shadowed it
        found += [f"the object {sha[:12]}" for sha in objects.split()]
    return found


def _preflight(repo: str, base: str, head: str) -> dict:
    """The scope of a review — the repository, both shas and their merge base — or an error envelope."""
    root = os.path.expanduser(repo)  # not Path.expanduser, which raises on a `~name` this machine does not know
    if not (Path(root) / ".git").exists():
        return {"status": "error", "error_message": f"{repo} is not a git repository (no .git directory)"}
    try:
        _, shallow = _git(root, "rev-parse", "--is-shallow-repository")
        if shallow == "true":  # cut at a depth, as CI checks out
            why = "a merge base found in one can be the wrong one: fetch its history first, git fetch --unshallow"
            return {"status": "error", "error_message": f"{repo} is a shallow clone, and {why}"}
        full = {}  # the one full ref each name resolved through, if a ref: a report names a tag it read
        for label, ref in (("base branch", base), ("head branch", head)):
            names = _namesakes(root, ref)
            full[label] = names[0] if names else ""
            if len(names) > 1:
                why = f"{label} {ref!r} is ambiguous: {' and '.join(names)}; name one in full"
                return {"status": "error", "error_message": why}
        base_sha, head_sha = _sha(root, base), _sha(root, head)
        if base_sha is None:
            return {"status": "error", "error_message": f"base branch {base!r} does not exist in {repo}"}
        if head_sha is None:
            return {"status": "error", "error_message": f"head branch {head!r} does not exist in {repo}"}
        # From here on git only sees commit hashes, which cannot be mistaken for options.
        code, merge_base = _git(root, "merge-base", base_sha, head_sha, ok=(0, 1))
        if code == 1:  # git's answer for two commits with no ancestor in common
            return {"status": "error", "error_message": f"{base!r} and {head!r} share no history: no change to review"}
        _, ahead = _git(root, "rev-list", "--count", f"{merge_base}..{head_sha}")
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    return {
        "status": "success",
        "repo": root,
        "base": base,
        "base_sha": base_sha,
        "head": head,
        "head_sha": head_sha,
        "merge_base": merge_base,
        "commits_ahead": int(ahead),
        "base_ref": full["base branch"],
        "head_ref": full["head branch"],
    }


def inspect_repository(repo: str, base: str, head: str, tool_context: ToolContext) -> dict:
    """Confirm `repo` is a git repository, that `base` and `head` exist, and find their merge base.

    Call this before anything else: the tools after it read the repository
    and branches it confirmed from session state and never ask for them
    again. Both branches must exist; a missing one is an error to report,
    never something to guess.

    Args:
        repo: Absolute path to the repository's root directory.
        base: The branch the change will be merged into, usually "main".
        head: The branch under review.

    Returns:
        On success: {"status": "success", "repo", "base", "base_sha", "head", "head_sha",
        "merge_base", "commits_ahead", "base_ref", "head_ref"}. On failure: {"status": "error", "error_message": "..."}.
    """
    resolved = _preflight(repo, base, head)
    # A failed preflight clears the scope: nothing later may read a repository this call did not confirm.
    tool_context.state["review_scope"] = resolved if resolved["status"] == "success" else None
    tool_context.state["review_files"] = None
    return resolved


def _changed(resolved: dict) -> list[dict[str, str]]:
    """`[{"path", "status"}]` for the change, from NUL-separated records so odd paths survive; a rename also carries
    its `old` path, `-M` finding renames whatever the reviewer's `diff.renames` says."""
    _, out = _git(
        resolved["repo"], "diff-tree", "-r", "--name-status", "-z", "-M", resolved["merge_base"], resolved["head_sha"]
    )
    parts = iter(p for p in out.split("\0") if p)
    files: list[dict[str, str]] = []
    for field in parts:
        status = field[0]
        # A rename (`R<score>`) or a copy (`C<score>`) names the old path first; the new one exists.
        old = {"old": next(parts)} if status in "RC" else {}
        files.append({"path": next(parts), "status": status, **old})
    return sorted(files, key=lambda f: f["path"])


def _literally(*paths: str) -> list[str]:
    """Pathspecs naming exactly these files: each path literal, and what lies inside a folder of that name left out,
    never the entry itself: measured, excluding `<name>/` hid a submodule, which git lists as a folder. From the
    top: without it Git for Windows reads a `\\` in a name as a folder's separator, and `c:x.py` as a drive."""
    specs = []
    for name in filter(None, paths):
        specs += [f":(top,literal){name}", f":(top,exclude,glob){_GLOB.sub(lambda m: '\\' + m.group(), name)}/**"]
    return specs


def _diff(resolved: dict, path: str, old: str = "") -> str:
    """One file's whole unified diff, as git prints it for no one's settings: the path taken literally, never as a
    pattern; the merge base's attributes, never the branch's own; no colour, no external diff, no text conversion.
    Measured: each of those once hid a planted key, the branch's `-diff` or a path spelled `:config.py` among them.
    `--attr-source` is git 2.41's. A rename is diffed with its `old` path too, so it reads as the lines it moved
    and changed; by the new path alone, it read as a whole file added. Each path is a file and never a folder:
    measured, `a` renamed to `b.py` beside a new `a/x.py` brought `a/x.py`'s key into `b.py`'s diff."""
    base, head = resolved["merge_base"], resolved["head_sha"]
    options = (f"--attr-source={base}",)
    flags = ("--no-color", "--no-ext-diff", "--no-textconv", "-M")
    _, diff = _git(
        resolved["repo"], *options, "diff-tree", "-r", "-p", *flags, base, head, "--", *_literally(old, path)
    )
    return diff


def _capped(diff: str) -> tuple[str, bool]:
    """The diff as a model may read it: cut at the cap, with the cut named."""
    if len(diff) <= DIFF_CAP_CHARS:
        return diff, False
    return diff[:DIFF_CAP_CHARS] + f"\n[… cut at {DIFF_CAP_CHARS:,} characters]", True


def changed_files(tool_context: ToolContext) -> dict:
    """List the files the branch under review changed, with a status letter each.

    Call this after inspect_repository and before show_diff: it reads the
    scope inspect_repository confirmed, and the paths it returns are the only
    paths show_diff will accept.

    Returns:
        On success: {"status": "success", "files": [{"path": ..., "status": "A|M|D|R", "old": ... for R}],
        "count": int}.
        On failure: {"status": "error", "error_message": "..."}.
    """
    scope = tool_context.state.get("review_scope")
    if not scope:
        return {"status": "error", "error_message": "call inspect_repository first; changed_files lists its change"}
    try:
        files = _changed(scope)
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    # The allowlist show_diff reads, each path with the old one a rename carries, so its diff reads both.
    tool_context.state["review_files"] = {f["path"]: f.get("old", "") for f in files}
    return {"status": "success", "files": files, "count": len(files)}


def show_diff(path: str, tool_context: ToolContext) -> dict:
    """The unified diff of one changed file, capped at 4,000 characters.

    Only a path that changed_files returned is accepted. A long diff is cut
    and the cut is marked in the text, so what you see is all you can cite.

    Args:
        path: A repository-relative path from changed_files.

    Returns:
        On success: {"status": "success", "path": ..., "diff": ..., "cut": bool}.
        On failure: {"status": "error", "error_message": "..."}.
    """
    scope = tool_context.state.get("review_scope")
    if not scope:
        return {"status": "error", "error_message": "call inspect_repository first; show_diff reads what it confirmed"}
    old = (tool_context.state.get("review_files") or {}).get(path, "")  # a rename is read with its old path
    try:
        diff, cut = _capped(_diff(scope, path, old))
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    return {"status": "success", "path": path, "diff": diff, "cut": cut}
