"""The project's own rules, one a file — a `Rule`, a `FileRule` or a `TreeRule`; the phase's `config.toml` groups
them into profiles.

Drop a file here and its rule is found and runs; a profile narrows what runs. `--profile NAME` is the one choice
about rules a review is given: every definition it reads is in this phase's folder, and nothing is read from the
repository under review. A file whose name starts with `_` is no rule file: `_template.py` is the copy-ready shape of
one. A rule may import `core` and the standard library, but nothing that runs a process, opens a network or reads
the environment (`os`, `subprocess` and `asyncio` among them), and runs nothing: `tests/test_layering.py` holds it to
that. A rule is for what no tool checks: ruff covers the rest, with the families `[lint]` selects, and `no_print.py`
duplicates ruff's T201, which `[lint]` leaves off, only as the example of the shape. `self_check` is a rule author's
first test: a rule that fires on its own source has read its own words.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Collection
from pathlib import Path
from typing import get_args

from ..core.findings import Severity
from ..core.rules import AnyRule, FileRule, Rule, lines_hit

#: The severities a rule may name.
SCALE = get_args(Severity)
#: What a rule names besides its severity, each a sentence the report prints.
PARTS = ("id", "title", "fix")


def discover() -> tuple[AnyRule, ...]:
    """Every `Rule`, `FileRule` and `TreeRule` defined in this folder's modules, a module named with a leading `_`
    left aside. A module that will not import, a rule missing a part, a severity the scale lacks or an id used twice
    is a sentence, never a rule quietly left out."""
    rules: dict[str, AnyRule] = {}
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_"):
            continue
        problem = None
        try:  # the project's own code runs from here on: whatever it raises, an exit too, is a sentence
            loaded = importlib.import_module(f"{__name__}.{module.name}")
            for kind in vars(loaded).values():
                if isinstance(kind, type) and issubclass(kind, AnyRule) and kind.__module__ == loaded.__name__:
                    if problem := _problem(rule := kind(), rules):
                        break
                    rules[rule.id] = rule
        except (Exception, SystemExit) as exc:  # noqa: BLE001 -- a rule file's own code: whatever it raises is named
            problem = f"{type(exc).__name__}: {exc}"
        if problem:
            raise ValueError(f"rules/{module.name}.py: {problem}")
    return tuple(rules[rule_id] for rule_id in sorted(rules))


def _problem(rule: AnyRule, taken: Collection[str]) -> str | None:
    """What keeps `rule` from being one whole rule, or None."""
    if not all(isinstance(getattr(rule, part, None), str) and getattr(rule, part) for part in PARTS):
        return f"{type(rule).__name__} needs an id, a title and a fix"
    if (severity := getattr(rule, "severity", None)) not in SCALE:
        return f"{rule.id!r} has severity {severity!r}, not {' or '.join(SCALE)}"
    if rule.id in taken:
        return f"the id {rule.id!r} is taken"
    return None


def self_check(rule: Rule | FileRule, path: str = "rules/a.py") -> list[int]:
    """The lines of the rule's own source its check fires on, read as added to `path`: a rule that reads its own
    words is a rule misread, so a rule's test asserts this is empty."""
    source = Path(inspect.getsourcefile(type(rule)) or "").read_text(encoding="utf-8")
    return lines_hit(rule, path, source)
