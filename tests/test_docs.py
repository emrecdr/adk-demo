"""The docs are pinned to the tree they describe: the map's folder tree, each phase README's file claims, and the
paths the guides name.

Three doc passes found the same rot by hand — a script or a test folder
missing from the map's tree, a README naming a file as unchanged after it
had changed. A test that reads the docs the way a reader does is cheaper than
a fourth pass — and it has to fail when a claim is missing, not only when one
is wrong: a README that classifies nothing would otherwise be checked for
nothing and pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import PHASES, ROOT, in_the_working_tree

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


def test_the_maps_tree_draws_every_file_in_the_working_tree_and_nothing_else() -> None:
    drawn, present = _tree_files(), in_the_working_tree()
    assert sorted(present - drawn - NOT_DRAWN) == [], "in the working tree but not in the map's tree"
    assert sorted(drawn - present - DRAWN_UNTRACKED) == [], "in the map's tree but not in the working tree"


#: The guides a reader or an assistant follows, held to the paths they name. The phase READMEs name other
#: repositories' paths too — the demo's `src/payments/charge.py`, a hostile branch's `X.py/y.py`, git's `refs/` — so
#: they are not among them.
GUIDES = [ROOT / "CLAUDE.md", ROOT / "README.md", *sorted((ROOT / ".github").rglob("*.md"))]
#: A backticked path with a folder in it: a file by the dot in its name, a folder by its trailing slash.
_PATH = re.compile(r"`((?:[\w.-]+/)+(?:[\w-]+\.[\w.]+)?)`")
#: The one path a guide names that no checkout holds: `adk web`'s session store, written when it runs.
NOT_IN_THE_REPOSITORY = {".adk/session.db"}


def _present(name: str) -> bool:
    """A file of the working tree or, ending in `/`, a folder one lies in — read from the root, or from inside a phase
    folder: only phase 7 has sub-packages, and the guides name its `core/blast.py` beside the phase, as its docs do."""
    present = in_the_working_tree()
    return any(
        root + name in present or (name.endswith("/") and any(p.startswith(root + name) for p in present))
        for root in ("", *(f"{phase}/" for phase in PHASES))
    )


@pytest.mark.parametrize("guide", GUIDES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_a_guide_names_only_paths_in_the_working_tree(guide: Path) -> None:
    named = set(_PATH.findall(guide.read_text(encoding="utf-8"))) - NOT_IN_THE_REPOSITORY
    missing = sorted(name for name in named if not _present(name))
    assert missing == [], f"{guide.relative_to(ROOT)} names paths that are not in the working tree"


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
