"""Phase 7's grouping IS its architecture: every import points one way, and the domain runs nothing.

Each group may import itself and the groups before it — `core`, then `rules` (a project's own), `collect`,
`judge`, `deliver` — and the two root modules, the loader's entry and the driver, may import anything. Read off
the syntax tree, so a new module is placed by where it sits, not by a list kept here — and once at runtime,
because the tree cannot see what importing a module loads.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from conftest import ROOT

PHASE = ROOT / "phase_7_hardened"
GROUPS = ("core", "rules", "collect", "judge", "deliver")
#: What the pure group may not touch: anything that calls a model, runs a process, or talks to a network.
#: Measured by review: `import socket` or `urllib.request` in a rule passed the test when this named no network.
FORBIDDEN_IN_CORE = ("google", "litellm", "subprocess", "httpx", "asyncio", "os", "socket", "urllib", "http", "ssl")


def _group(path: Path) -> str:
    parts = path.relative_to(PHASE).parts
    return parts[0] if len(parts) > 1 else "root"


def _rank(group: str) -> int:
    return GROUPS.index(group) if group in GROUPS else len(GROUPS)


def _relative_imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            target = path.parents[node.level - 1] / (node.module or "").replace(".", "/")
            yield node, target


def test_no_group_imports_a_group_after_it() -> None:
    upward = []
    for path in sorted(PHASE.rglob("*.py")):
        for node, target in _relative_imports(path):
            source_group, target_group = _group(path), _group(target)
            if node.module is None:  # `from . import x`: x names the module or package
                target_group = _group(target / node.names[0].name)
            if _rank(target_group) > _rank(source_group):
                upward.append(f"{path.relative_to(PHASE)} imports {target_group} ({source_group} may not)")
    assert upward == [], "\n".join(upward)


def test_the_report_needs_only_the_domain() -> None:
    """The report renders what the driver hands it: the sources that ran, in order, and the spend as text. Measured
    by review: it imported the lane table, the ledger and the lint gate's name, and with them 155 ADK modules, for
    text it could simply be given."""
    reached = {_group(target) for path in (PHASE / "deliver").glob("*.py") for _node, target in _relative_imports(path)}
    assert reached <= {"core", "deliver"}, reached


def test_the_phase_imports_its_own_modules_only_relatively() -> None:
    """The direction test reads relative imports, the form every module here uses; an import spelled from the top,
    `phase_7_hardened.…`, would pass it whatever it pointed at. Measured by review: `from phase_7_hardened.judge
    .lanes import state_key`, planted in `collect/gates.py`, passed every test in this file."""
    absolute = []
    for path in sorted(PHASE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            absolute += [f"{path.relative_to(PHASE)}: {n}" for n in names if n.split(".")[0] == PHASE.name]
    assert absolute == [], absolute


def test_the_core_runs_nothing_and_knows_no_model() -> None:
    offenders = []
    for path in sorted([*(PHASE / "core").glob("*.py"), *(PHASE / "rules").glob("*.py")]):  # a rule runs nothing too
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN_IN_CORE]
    assert offenders == [], offenders


def test_every_group_says_what_it_may_import() -> None:
    """The rule lives in the code as well: each package docstring states its own boundary."""
    for group in GROUPS:
        text = (PHASE / group / "__init__.py").read_text(encoding="utf-8")
        assert "import" in text.lower(), f"{group}/__init__.py does not say what it may import"


def test_the_core_imports_with_adk_absent_and_loads_none_of_what_it_may_not() -> None:
    """The claim at runtime: `core/` and the project's rules can be read and tested without ADK installed. A fresh
    interpreter makes `google` unimportable, imports every core module and every rule, and reports what came with
    them — measured before the package root stopped importing the agent module: 187 ADK modules, then a
    `ModuleNotFoundError` with ADK absent."""
    modules = sorted(f"phase_7_hardened.core.{p.stem}" for p in (PHASE / "core").glob("*.py") if p.stem != "__init__")
    forbidden = [m for m in FORBIDDEN_IN_CORE if m != "os"]  # the interpreter itself imports os
    probe = (
        "import sys\n"
        "sys.modules['google'] = None  # an import of it raises, as it does when ADK is not installed\n"
        f"for name in {modules!r}:\n    __import__(name)\n"
        "from phase_7_hardened.rules import discover\n"
        "assert discover(), 'the rules folder holds one rule at least'\n"
        f"loaded = [m for m in sys.modules if sys.modules[m] and m.split('.')[0] in {forbidden!r}]\n"
        "loaded += [m for m in sys.modules if m.split('.')[0] == 'phase_7_hardened' and m.count('.')\n"
        "           and m.split('.')[1] not in ('core', 'rules')]\n"
        "print(sorted(loaded))\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, encoding="utf-8", check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout
