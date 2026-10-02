"""The docs are pinned to the tree they describe: the map's folder tree, and each phase README's file claims.

Three doc passes found the same rot by hand — a script or a test folder
missing from the map's tree, a README naming a file as unchanged after it
had changed. A test that reads the docs the way a reader does is cheaper than
a fourth pass — and it has to fail when a claim is missing, not only when one
is wrong: a README that classifies nothing would otherwise be checked for
nothing and pass.
"""

from __future__ import annotations

import re
import subprocess

import pytest
from conftest import PHASES, ROOT

MAP = ROOT / "docs" / "ITERATION_MAP.md"
#: Files the tree leaves out on purpose, and the one file it draws that git ignores.
NOT_DRAWN = {"uv.lock", ".gitignore"}
DRAWN_UNTRACKED = {".env"}


def _tree_files() -> set[str]:
    """Every file the map's section 3 tree draws, as a repository-relative path."""
    section = MAP.read_text(encoding="utf-8").split("## 3. Shape of the repository", 1)[1]
    block = section.split("```", 2)[1]
    stack: list[str] = []
    files: set[str] = set()
    for line in block.splitlines()[1:]:  # the first line is the root folder itself
        match = re.match(r"^((?:[│ ]   )*)[├└]── (\S+)", line)
        if match is None:
            continue
        depth = len(match.group(1)) // 4
        name = match.group(2)
        stack = stack[:depth]
        if name.endswith("/"):
            stack.append(name.rstrip("/"))
        else:
            files.add("/".join([*stack, name]))
    assert len(files) > 20, "the map's tree block did not parse: its fences or its indentation changed"
    return files


def _in_the_working_tree() -> set[str]:
    """Tracked files plus new ones git does not ignore: a file is drawn before it is committed, not after."""
    argv = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    done = subprocess.run(argv, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)
    return set(done.stdout.split())


def test_the_maps_tree_draws_every_file_in_the_working_tree_and_nothing_else() -> None:
    drawn, present = _tree_files(), _in_the_working_tree()
    assert sorted(present - drawn - NOT_DRAWN) == [], "in the working tree but not in the map's tree"
    assert sorted(drawn - present - DRAWN_UNTRACKED) == [], "in the map's tree but not in the working tree"


def test_the_map_has_a_section_per_phase() -> None:
    text = MAP.read_text(encoding="utf-8")
    for number in range(1, len(PHASES) + 1):
        assert re.search(rf"^## \d+\. Phase {number} — ", text, re.M), f"no section for phase {number}"


#: A claim reads `New: `a`, `b`.` — or Changed, Unchanged, Gone — anywhere in a phase README, bold or not.
_CLAIM = re.compile(r"(New|Changed|Unchanged|Gone|Moved): ((?:`[^`]+`(?:,\s+)?)+)\.")  # a list may wrap a line


def _claims(text: str) -> dict[str, str]:
    """`{file: claim}` as the README states it; a file classified twice is the README's error, reported as one."""
    out: dict[str, str] = {}
    for claim, names in _CLAIM.findall(text):
        for name in re.findall(r"`([^`]+)`", names):
            assert name not in out, f"{name} is classified twice: {out[name]} and {claim}"
            out[name] = claim
    return out


@pytest.mark.parametrize("phase", PHASES)
def test_each_phase_readme_classifies_every_file_truthfully(phase: str) -> None:
    """Every Python file is New, Changed or Unchanged since the previous phase — exactly one of the three, and
    truthfully: New was absent before, Changed is in both and differs, Unchanged is byte-identical, Gone was there
    and is not any more, Moved was there and now sits in a subfolder. The first phase has no previous one, so it
    only has to name what it holds."""
    here = ROOT / phase
    text = (here / "README.md").read_text(encoding="utf-8")
    files = {p.name for p in here.glob("*.py")}
    index = PHASES.index(phase)
    if index == 0:
        assert [n for n in sorted(files) if f"`{n}`" not in text] == [], f"{phase}/README.md never names these"
        return
    previous = ROOT / PHASES[index - 1]
    before = {p.name for p in previous.glob("*.py")}
    claims = _claims(text)
    left = {"Gone", "Moved"}
    assert {n for n, c in claims.items() if c not in left} == files, (
        f"{phase}/README.md must classify exactly its files"
    )
    assert {n for n, c in claims.items() if c in left} == before - files, f"{phase}/README.md must name what left"
    for name in (n for n, c in claims.items() if c == "Moved"):
        assert list(here.rglob(name)), f"{phase}: {name} is called moved but is nowhere under the folder"
    for name, claim in claims.items():
        same = name in before and name in files and (here / name).read_bytes() == (previous / name).read_bytes()
        if claim == "New":
            assert name not in before, f"{phase}: {name} already existed in {previous.name}"
        elif claim == "Changed":
            assert name in before and not same, f"{phase}: {name} is not a change from {previous.name}"
        elif claim == "Unchanged":
            assert same, f"{phase}: {name} differs from {previous.name}'s"
