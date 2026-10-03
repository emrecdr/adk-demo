"""A rule, ready to copy. Five steps, then it runs.

1. Copy this file under the rule's own name, `no_sleep.py` say. Discovery skips a file whose name starts with `_`,
   so this template never runs, and the copy runs at once: in `default`, until a profile in `config.toml` leaves it
   off.
2. Fill in the four lines below: `id`, `severity`, `title`, `fix`.
3. Write `check`. Pick the smallest thing that answers the question — a line, a file, the tree:
   a `Rule` reads each line the change added, one at a time (this file);
   a `FileRule` reads each file the change touched, whole at the head — `file.lines`, `file.added`, `file.module`;
   a `TreeRule` reads the head's tree — `tree.has(path)`, `tree.module(path)`, `tree.modules()`.
   `README.md` beside this file shows one of each. A rule reads only what it is given and runs nothing; its
   expectations are constants here, beside the check.
4. See it, and try it on a repository, with no model and no key:
   `uv run python -m phase_7_hardened.review --list-rules`
   `uv run python -m phase_7_hardened.review <repo> --base main --check <id>`
5. Test it in `tests/`: `lines_hit(rule, path, text)` from `core/rules.py` for what it flags and what it leaves
   alone, and `self_check(rule)` from this folder — a rule that fires on its own source has read its words, not code.
"""

from __future__ import annotations

import tokenize

from ..core.rules import Rule, tokens

#: What the rule looks for, named once here: the reader of a finding reads the title and the fix, the reader of the
#: rule reads this and the check.
MARKER = "TODO"


class Template(Rule):
    """One sentence on why a project wants this rule — what goes wrong when the shape it names is merged."""

    id = "template"  # kebab-case and unique: a profile names the rule by it, and the report prints it
    severity = "minor"  # blocker: must not merge; major: fix before merge; minor: worth fixing
    title = "a marker left in the code"  # one line naming the problem, as the report prints it
    fix = "Resolve it before merging, or move it to the tracker."  # what to change, concretely

    def check(self, path: str, line: str) -> bool:
        """True when `line`, added to `path`, breaks the rule. `tokens(line)` reads the line as Python does, so a word
        in a comment can be told from one in code or in a string; `path` lets a rule choose its files."""
        return path.endswith(".py") and any(
            token.type == tokenize.COMMENT and MARKER in token.string for token in tokens(line)
        )
