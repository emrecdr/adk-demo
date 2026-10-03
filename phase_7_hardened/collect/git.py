"""Read-only git, gathered without a model.

Git runs as an argv list with a timeout, never through a shell, only with
verbs that read, decoded as UTF-8. `preflight` and `collect_evidence` answer
as envelopes, for the driver and the tools; the helpers between them return
bare values, for code. `collect_evidence` runs the same calls in plain Python
so the driver can gather everything the gates, the rules and the lanes read
before any model is called. Nothing here knows ADK: the model-facing tools
that wrap these live in `judge/tools.py`.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..core.blast import Blast, blast_radius
from ..core.rules import Tree
from ..core.text import cut_at, squash

GIT_TIMEOUT_S = 30
#: Every string the model reads is capped in characters, and the cut is named.
DIFF_CAP_CHARS = 4_000
#: And the block of diffs the lanes read, in all: a file past it is left out whole, and named. Measured with none,
#: `--all` over 4,826 files gave each lane and each verifier 14.9 MB; this repository's whole project, 275,688
#: characters, was 80,000 tokens a lane, answered on Copilot; the planted branch is 2,205.
BLOCK_CAP_CHARS = 250_000
_HUNK_START = re.compile(r"^@@ -\S+ \+(\d+)(,0\b)?")
#: The tree the blast radius reads is bounded, and what is not read is counted: over a partial tree a count is a
#: floor, and says so. Measured at 80 to 142 ms a megabyte to parse and resolve (ADK's 6.3 MB, LiteLLM's 32.3);
#: a file cap alone let a branch of 5,000 one-megabyte files in. The largest real file seen was 0.8 MB.
MAX_TREE_BYTES = 20_000_000
MAX_FILE_BYTES = 1_000_000
#: The tree of no files, by the repository's hash: git knows it without storing it. A whole-project review diffs the
#: head against it, so every file reads as added and goes through the gates, the lanes and grounding as a change does.
EMPTY_TREE = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}


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


def on_path(name: str) -> str:
    """`name` by its full path, as PATH finds it, never from the current directory: Windows looks there first, and
    the current directory can be the checkout under review, whose own `git.exe` must never run. Not found, the name
    alone, which is never launched: Windows would look for a bare name in the current directory too."""
    return _found(name, os.environ.get("PATH", ""))


@functools.cache
def _found(name: str, path: str) -> str:
    """Once per PATH: on Windows each lookup tries every PATHEXT."""
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"  # read by `shutil.which` on Windows, ignored elsewhere
    return shutil.which(name, path=path) or name


def _run(argv: list[str], env: dict[str, str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """One command, bytes in and out, stopped whole past `GIT_TIMEOUT_S`. Git for Windows' `git.exe` runs the real
    git as its child, which holds the output open; `subprocess.run` kills only the first and then, on Windows, reads
    the output to its end, so a git past its timeout hung the review. There the whole tree is stopped first."""
    with subprocess.Popen(
        argv, stdin=None if stdin is None else subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    ) as process:
        try:
            out, err = process.communicate(stdin, timeout=GIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            if os.name == "nt":  # the tree, then the output to its end, which Windows reads on threads
                taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                subprocess.run([taskkill, "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
                process.communicate()
            process.kill()
            raise
    return subprocess.CompletedProcess(argv, process.returncode, out, err)


def _git(repo: str, *args: str, strip: bool = True, ok: tuple[int, ...] = (0,)) -> tuple[int, str]:
    """One read-only git command: an argv list, no shell, a timeout, no fetch, stdout captured, decoded as UTF-8.

    An exit code outside `ok` raises `GitError` with git's own first line, and so does a call past the timeout,
    killed, naming the limit, for the envelope to answer: some answers below are read without their exit
    code, and a failure read as an empty answer would read as nothing there. `ok` names the codes a caller
    reads as an answer: 1 is `rev-parse`'s for a ref that does not exist. `strip` is off for a file's content,
    where the line numbers must survive.
    """
    done = _git_raw(repo, *args, ok=ok)
    # Decoded here, never in text mode, which reads a lone `\r` inside a line of a file as a line break.
    out = done.stdout.decode("utf-8", "replace")
    return done.returncode, out.strip() if strip else out


def _git_raw(
    repo: str, *args: str, stdin: bytes | None = None, ok: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess[bytes]:
    """`_git`'s call with its answer left as bytes, what a batch read counts its sizes in."""
    if (git := on_path("git")) == "git":  # not on PATH: Git for Windows can be installed for Git Bash alone
        raise GitError(f"git {_verb(args)} could not start: git is not on PATH")
    try:
        done = _run([git, "-C", repo, *args], _environment(repo), stdin)
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
    return done


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


def preflight(repo: str, base: str | None, head: str) -> dict:
    """The scope of a review — the repository, both shas and their merge base — or an error envelope. With no base,
    the whole project at the head: the empty tree stands for the base and the merge base, and a shallow clone
    serves, since no merge base is looked for."""
    root = os.path.expanduser(repo)  # not Path.expanduser, which raises on a `~name` this machine does not know
    if not is_repository(root):
        return {"status": "error", "error_message": f"{repo} is not a git repository (no .git directory)"}
    try:
        if base is not None:
            _, shallow = _git(root, "rev-parse", "--is-shallow-repository")
            if shallow == "true":  # cut at a depth, as CI checks out
                why = "a merge base found in one can be the wrong one: fetch its history first, git fetch --unshallow"
                return {"status": "error", "error_message": f"{repo} is a shallow clone, and {why}"}
        full: dict[str, str] = {}  # the one full ref each name resolved through, if a ref: a report names a tag
        for label, ref in (("base branch", base), ("head branch", head)):
            names = _namesakes(root, ref) if ref is not None else []
            full[label] = names[0] if names else ""
            if len(names) > 1:
                why = f"{label} {ref!r} is ambiguous: {' and '.join(names)}; name one in full"
                return {"status": "error", "error_message": why}
        base_sha, head_sha = _sha(root, base) if base is not None else "", _sha(root, head)
        if base_sha is None:
            return {"status": "error", "error_message": f"base branch {base!r} does not exist in {repo}"}
        if head_sha is None:
            return {"status": "error", "error_message": f"head branch {head!r} does not exist in {repo}"}
        # From here on git only sees commit hashes, which cannot be mistaken for options.
        if base is None:
            _, form = _git(root, "rev-parse", "--show-object-format")
            base_sha = merge_base = EMPTY_TREE[form]
            span = head_sha
        else:
            code, merge_base = _git(root, "merge-base", base_sha, head_sha, ok=(0, 1))
            if code == 1:  # git's answer for two commits with no ancestor in common
                why = f"{base!r} and {head!r} share no history: no change to review"
                return {"status": "error", "error_message": why}
            span = f"{merge_base}..{head_sha}"
        _, ahead = _git(root, "rev-list", "--count", span)
    except GitError as exc:
        return {"status": "error", "error_message": str(exc)}
    return {
        "status": "success",
        "repo": root,
        "base": base or "",
        "base_sha": base_sha,
        "head": head,
        "head_sha": head_sha,
        "merge_base": merge_base,
        "commits_ahead": int(ahead),
        "base_ref": full["base branch"],
        "head_ref": full["head branch"],
    }


def is_repository(repo: str) -> bool:
    """A repository of its own, never a folder inside one, whose git would answer for the repository around it."""
    return (Path(os.path.expanduser(repo)) / ".git").exists()


def checked_out(repo: str) -> str | None:
    """The branch the repository has checked out, or None where none is: a detached head, as CI checks out."""
    code, out = _git(repo, "symbolic-ref", "--short", "--quiet", "HEAD", ok=(0, 1))
    return out if code == 0 else None


def default_base(repo: str) -> str | None:
    """What a change is compared with when no base is named: `main`, or `master` where there is no `main`."""
    return next((name for name in ("main", "master") if _sha(repo, f"refs/heads/{name}") is not None), None)


def in_scope(path: str, scope: Sequence[str]) -> bool:
    """Whether a changed file is one of `scope`'s, or lies under one of its folders; no scope holds every file."""
    return not scope or any(path == folder or path.startswith(f"{folder}/") for folder in scope)


def list_changed(resolved: dict) -> list[dict[str, str]]:
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


#: How `diff_of` and `whole_diffs` call git: no colour, no external diff, no text conversion, renames found.
_PLAIN = ("--no-color", "--no-ext-diff", "--no-textconv", "-M")


def diff_of(resolved: dict, path: str, old: str = "") -> str:
    """One file's whole unified diff, as git prints it for no one's settings and with "\\n" its only line break: the
    path taken literally, never as a pattern; the merge base's attributes, never the branch's own; no colour, no
    external diff, no text conversion.
    Measured: each of those once hid a planted key, the branch's `-diff` or a path spelled `:config.py` among them.
    `--attr-source` is git 2.41's. A rename is diffed with its `old` path too, so it reads as the lines it moved
    and changed; by the new path alone, it read as a whole file added. Each path is a file and never a folder:
    measured, `a` renamed to `b.py` beside a new `a/x.py` brought `a/x.py`'s key into `b.py`'s diff."""
    repo, base, head = resolved["repo"], resolved["merge_base"], resolved["head_sha"]
    _, diff = _git(
        repo, f"--attr-source={base}", "diff-tree", "-r", "-p", *_PLAIN, base, head, "--", *_literally(old, path)
    )
    return readable(diff)


def whole_diffs(resolved: dict, entries: list[dict[str, str]], scope: Sequence[str]) -> list[str]:
    """Under `--all`, each entry's diff as `diff_of` reads it, from one call split at each `diff --git` opening a line.

    Every file is added, so each has one such header, and no line of a file can open one: each is marked `+`.
    Measured over 4,826 files: 9.4 s a call a file, eight at a time; 0.86 s in one."""
    repo, base, head = resolved["repo"], resolved["merge_base"], resolved["head_sha"]
    specs = ("--", *(f":(top,literal){folder}" for folder in scope))
    _, names = _git(repo, "diff-tree", "-r", "-z", "--name-only", "-M", base, head, *specs, strip=False)
    paths = names.split("\0")[:-1]
    # Split as bytes, each part decoded alone: one str of the whole patch is as wide as its widest character.
    args = (f"--attr-source={base}", "diff-tree", "-r", "-p", *_PLAIN, base, head, *specs)
    parts = re.split(rb"(?m)^(?=diff --git )", _git_raw(repo, *args).stdout)[1:]  # the whole, freed once split
    if len(parts) != len(paths) or sorted(paths) != [entry["path"] for entry in entries]:
        raise GitError("git diff-tree's one patch did not split into the files it lists")
    pairs = sorted(zip(paths, parts, strict=True), key=lambda pair: pair[0])  # as `list_changed` sorts git's order
    return [readable(part.decode("utf-8", "replace").strip()) for _, part in pairs]


#: How many git processes run at once where a change asks one per file. Measured on a branch of 224 files: its
#: diffs took 1,347 ms one at a time and 292 ms eight at a time, and sixteen did no better. git's own batch for
#: diffs, `diff-pairs`, would take 25 ms, but it came with git 2.50, and this reviewer asks for 2.41.
GIT_WORKERS = 8


def _listed(resolved: dict) -> list[tuple[str, str, str, str, str]]:
    """The head's tree, one `(mode, kind, sha, size, path)` an entry, NUL-separated so any path holds; raises
    `GitError`, never an empty tree."""
    _, listing = _git(resolved["repo"], "ls-tree", "-r", "-l", "-z", resolved["head_sha"], strip=False)
    entries = []
    for record in filter(None, listing.split("\0")):
        meta, _, path = record.partition("\t")
        mode, kind, sha, size = meta.split()
        entries.append((mode, kind, sha, size, path))
    return entries


def _blobs(resolved: dict, shas: Sequence[str]) -> list[str | None]:
    """Each blob's text, in order, from one `cat-file --batch`; None for one git did not give back, as a partial
    clone's missing blob, never fetched. Asked by object name, so no path splits the input, and read as bytes, since
    git counts sizes in bytes and text mode would rewrite CRLF. A failed call raises `GitError`, as `_git`'s does."""
    out = _git_raw(resolved["repo"], "cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in shas).encode()).stdout
    texts: list[str | None] = [None] * len(shas)
    at = 0
    for index in range(len(shas)):
        end = out.find(b"\n", at)
        if end < 0:  # the answer stopped early: what it did not reach was not read
            break
        header, at = out[at:end].split(), end + 1
        if len(header) == 3:  # else `<name> missing`, and no content follows
            size = int(header[2])
            texts[index] = out[at : at + size].decode("utf-8", errors="replace")
            at += size + 1
    return texts


def files_at_head(resolved: dict, paths: Sequence[str]) -> list[str]:
    """Each of `paths` at the head commit, in order, in two git processes whatever their number: on `--all` over
    4,826 files, one `git show` each took 16.5 s. A path the head holds as no file raises, never reads as empty."""
    blobs = {path: sha for _mode, kind, sha, _size, path in _listed(resolved) if kind == "blob"}
    if absent := [path for path in paths if path not in blobs]:
        raise GitError(f"git ls-tree lists no file {absent[0]!r} at the head")
    texts = _blobs(resolved, [blobs[path] for path in paths])
    if None in texts:
        raise GitError(f"git cat-file did not give back {paths[texts.index(None)]!r}")
    return texts


def tree_at_head(resolved: dict, listing: list[tuple[str, str, str, str, str]] | None = None) -> Tree | None:
    """The head's tree: every path, every Python file read and parsed once, and the Python files not read; None when
    the tree could not be listed.

    Two processes whatever the tree's size: `ls-tree -l` names each blob with its size, so a file over
    its cap or past the tree's costs nothing, and one batch reads the rest. A link is skipped uncounted: its target
    is read under its own name. A failed or timed-out listing is None, never an empty tree: measured with its exit
    code ignored, every changed file read as "a leaf". A batch past its timeout reads nothing, and every file it
    was asked for is named unread; so is a blob a partial clone lacks, which git lists with no size. A `listing`
    already taken is read instead of a second one.
    """
    if listing is None:
        try:
            listing = _listed(resolved)
        except GitError:
            return None
    paths = [path for _mode, _kind, _sha, _size, path in listing]
    python = (
        (path, sha, size)
        for mode, kind, sha, size, path in listing
        if kind == "blob" and mode != "120000" and path.endswith(".py")
    )
    wanted, unread = _budgeted(python)
    sources = _read(resolved, wanted)
    return Tree(paths, sources, unread + [path for path, _ in wanted if path not in sources])


def _budgeted(blobs: Iterable[tuple[str, str, str]]) -> tuple[list[tuple[str, str]], list[str]]:
    """Which of the `(path, sha, size)` blobs to read, each within its cap and all within the tree's budget, in
    order; and the paths left unread — one over its cap, past the budget, or sized "BAD", as a partial clone lists
    a blob it lacks, which nothing fetches to size."""
    wanted: list[tuple[str, str]] = []
    unread: list[str] = []
    budget = MAX_TREE_BYTES
    for path, sha, size_field in blobs:
        size = int(size_field) if size_field.isdigit() else None
        if size is None or size > min(MAX_FILE_BYTES, budget):
            unread.append(path)
        else:
            wanted.append((path, sha))
            budget -= size
    return wanted, unread


def _read(resolved: dict, wanted: list[tuple[str, str]]) -> dict[str, str]:
    """The text of each `(path, sha)` wanted, by path, from one batch. A blob the batch did not give back, or a batch
    that failed or timed out and so read nothing, leaves its path out, for the caller to name unread."""
    try:
        texts = _blobs(resolved, [sha for _path, sha in wanted]) if wanted else []
    except GitError:
        texts = [None] * len(wanted)
    return {path: text for (path, _sha), text in zip(wanted, texts, strict=True) if text is not None}


def read_texts(resolved: dict, files: list[dict], listing: list[tuple[str, str, str, str, str]] | None) -> None:
    """Each changed file's text at the head, for the file rules, set on its entry as `text`: a plain file the head
    holds within the caps, read in one batch. `unread_text` names one the head holds that was not read — over its
    cap, past the tree's budget, a blob the batch did not give back, or a tree that could not be listed — a hole for
    a rule that reads it. A file the head does not hold, a binary, a link or a submodule has neither: nothing for a
    file rule to read, and the report names a binary under not read already."""
    for entry in files:
        entry["text"], entry["unread_text"] = None, None
    if listing is None:
        for entry in files:
            entry["unread_text"] = "was not read: the head's tree could not be listed"
        return
    blobs = {path: (sha, size) for mode, kind, sha, size, path in listing if kind == "blob" and mode != "120000"}
    changed = [entry for entry in files if entry["path"] in blobs and not _BINARY.search(entry["diff"])]
    wanted, _over = _budgeted((entry["path"], *blobs[entry["path"]]) for entry in changed)
    texts = _read(resolved, wanted)
    for entry in changed:
        if entry["path"] in texts:
            entry["text"] = texts[entry["path"]]
        else:
            entry["unread_text"] = "was not read whole"


def radius_of(tree: Tree | None, files: list[dict]) -> Blast:
    """What at the head depends on each changed file, from the tree `tree_at_head` gave, so the head is parsed once
    for the radius and the tree rules alike; None, a tree not listed, is a floor."""
    if tree is None:
        return blast_radius({}, files, listed=False)
    return blast_radius(tree.parsed, files, len(tree.unread))


#: What a reader, or `str.splitlines`, breaks a line at besides "\n": a lone `\r`, a form feed, U+2028 among them.
_BREAKS = re.compile("[\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")
_BINARY = re.compile(r"^Binary files .* differ$", re.MULTILINE)
_SUBMODULE = re.compile(r"^(?:new file mode|index \S+) 160000$", re.MULTILINE)


def readable(diff: str) -> str:
    """The diff with "\\n" its only line break: a CRLF file's `\\r` dropped, every other break shown as its escape.
    Measured: a lone `\\r` in an added line split it, so the key after it was no added line for the gate; and text
    after a form feed, with no diff marker, read as the prompt's own."""
    return _BREAKS.sub(lambda m: m.group().encode("unicode_escape").decode(), diff.replace("\r\n", "\n"))


def unread(entry: dict, diff: str, cut: bool, fits: bool = True) -> str:
    """Why the lanes could not read all of a changed file, or "" when they could: named, never read as "found
    nothing". A deleted file adds nothing: what it removes was reviewed when it came in. `fits` is False for a
    file past the block's cap."""
    if entry["status"] == "D":
        return ""
    if not diff.strip():
        return "git showed none of it"
    if _SUBMODULE.search(diff):
        return "a submodule: its commits are another repository's, not read here"
    if _BINARY.search(diff):
        return "binary: no line of it can be read or quoted"
    if not fits:
        return f"past the {BLOCK_CAP_CHARS:,} characters the lanes read in all; --path narrows a review"
    if cut:
        return f"cut at {DIFF_CAP_CHARS:,} characters: the lanes read only its start"
    return ""


def _fence(text: str) -> str:
    """A code fence longer than any run of backticks in `text`: measured, a markdown file's own fence of three,
    a context line of the change, closed the fence of three the change was written in."""
    return "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))


def _hunk_lines(diff: str) -> Iterator[tuple[int, str]]:
    """`(new line number, line)` for every line inside the diff's hunks — added, removed or context, marker kept.

    The one place unified-diff syntax is read. Git's file headers come before
    the first `@@`, and inside a hunk anything that is not a change or context
    line — the next hunk's header, git's `\\ No newline at end of file`, the
    cap's cut marker — is not a line of the file. A removed line carries the
    number of the new line before it, 0 when there is none. Git names an empty
    range by the line before it: measured, `+0,0`, a deleted file's hunk, read
    as the line after it numbered every removed line -1.
    """
    new_line, in_hunk = 0, False
    for raw in diff.split("\n"):  # git's line break, and no other
        if hunk := _HUNK_START.match(raw):
            new_line, in_hunk = int(hunk.group(1)) - (hunk.group(2) is None), True
        elif in_hunk and raw[:1] in ("+", "-", " "):
            if raw[:1] != "-":  # a removed line is not in the new file
                new_line += 1
            yield new_line, raw


def added_lines(diff: str) -> list[tuple[int, str]]:
    """`(new line number, text)` for every line the change added: a gate that needs "what was added, and where"
    takes this list, never the diff."""
    return [(number, raw[1:]) for number, raw in _hunk_lines(diff) if raw[:1] == "+"]


def quotable(diff: str) -> list[tuple[int, str]]:
    """`(new line number, line)` for the lines a lane may quote from one file's diff as it read it, markers kept:
    nothing git or the cap wrote around them, which a finding could otherwise quote and pass as grounded."""
    return list(_hunk_lines(diff))


def capped(diff: str) -> tuple[str, bool]:
    """The diff as a model may read it: cut at the cap, with the cut named on a line of its own."""
    return cut_at(diff, DIFF_CAP_CHARS, sep="\n"), len(diff) > DIFF_CAP_CHARS


def collect_evidence(repo: str, base: str | None, head: str, scope: Sequence[str] = ()) -> dict:
    """Everything the gates, the rules and the lanes read, gathered in plain Python before any model runs.

    `files` carries each changed file with its WHOLE diff and its numbered
    added lines, for the gates, its text at the head, for the file rules, and the lines of its capped diff a lane
    may quote, numbered too, for grounding; `diff` is the rendered block the lanes read —
    one `### <path>` heading and a fenced diff per file, in path order, each
    capped and the block too, what it leaves out counted at its end, each path
    flattened because a newline in one forged a heading —
    the same block the chat-mode intake agent assembles through its
    tools; `blast` is what at the head depends on each changed file, which the
    lanes read beside that block and never inside it; `tree` is the head as the tree rules read it, or None where
    it could not be listed. One `git diff-tree -p` per file
    of a branch, never one for all of them split afterwards: git documents no reliable way to
    split a patch by file, and measured, a header can name two paths ambiguously
    and a type change prints two headers for one file; under `--all`, where every
    file is added, `whole_diffs` splits one safely. A branch's diffs run
    `GIT_WORKERS` at a time, which a profile with no lane, and so no model to
    wait on, made worth it. With no `base`, every file at the head is the
    change, and `whole` says so; with a `scope`, only what lies under its folders is, and
    `outside` counts what was left out, for the report to name.
    """
    resolved = preflight(repo, base, head)
    if resolved["status"] != "success":
        return resolved
    files, blocks = [], []
    try:
        listed = list_changed(resolved)
        entries = [entry for entry in listed if in_scope(entry["path"], scope)]
        if base is None:  # every file is added: one call reads them all
            diffs = whole_diffs(resolved, entries, scope)
        else:
            with ThreadPoolExecutor(max_workers=GIT_WORKERS) as pool:  # git processes to wait on: threads suffice
                diffs = list(pool.map(lambda entry: diff_of(resolved, entry["path"], entry.get("old", "")), entries))
        room, left_out = BLOCK_CAP_CHARS, 0
        for entry, diff in zip(entries, diffs, strict=True):
            shown, cut = capped(diff)
            block = f"### {squash(entry['path'])}\n{_fence(shown)}diff\n{shown}\n{_fence(shown)}"
            fits = len(block) <= room
            files.append(
                {
                    **entry,
                    "diff": diff,
                    "added": added_lines(diff),
                    "quotable": quotable(shown) if fits else [],  # no lane read it, so none may quote it
                    "unread": unread(entry, diff, cut, fits),
                    "cut": cut or not fits,  # the lanes' limits alone: the gates and the rules read every added line
                }
            )
            if fits:
                blocks.append(block)
                room -= len(block) + 2  # and the blank line joining it to the next
            else:
                left_out += 1
        if left_out:  # named to the lanes too: a test left out is no test missing
            blocks.append(f"[… {left_out} more file(s) not shown: past {BLOCK_CAP_CHARS:,} characters in all]")
    except GitError as exc:  # the change half read is not the change: named, never reviewed as it stands
        return {"status": "error", "error_message": str(exc)}
    if not files:  # measured: a branch already merged, or a base equal to its head, approved a review of nothing
        return {"status": "error", "error_message": _nothing(head, base, scope if listed else ())}
    try:
        listing = _listed(resolved)
    except GitError:
        listing = None
    tree = tree_at_head(resolved, listing)
    read_texts(resolved, files, listing)
    blast = radius_of(tree, files)
    return {
        "status": "success",
        "preflight": resolved,
        "files": files,
        "diff": "\n\n".join(blocks),
        "blast": blast,
        "tree": tree,
        "whole": base is None,
        "scope": list(scope),
        "outside": len(listed) - len(entries),
    }


def _nothing(head: str, base: str | None, scope: Sequence[str]) -> str:
    """Why there is nothing to review: the head holds no file, adds nothing to the base, or nothing under the scope."""
    if scope:
        what = f"no file at {head!r}" if base is None else f"nothing {head!r} changes"
        return f"{what} lies under {', '.join(scope)}: no change to review"
    if base is None:
        return f"{head!r} holds no file: nothing to review"
    return f"{head!r} adds nothing to {base!r}: no change to review"
