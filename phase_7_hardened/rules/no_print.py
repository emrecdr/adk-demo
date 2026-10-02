"""A project's own rule, as an example of the shape: one file, one self-contained `Rule`."""

from __future__ import annotations

import tokenize
from itertools import pairwise

from ..core.blast import is_test
from ..core.rules import Rule, tokens


class NoPrint(Rule):
    """print() in library code writes to whoever runs it, where a logger can be turned down or sent elsewhere."""

    id = "no-print"
    severity = "minor"
    title = "print() left in library code"
    fix = "Use the logger."

    def check(self, path: str, line: str) -> bool:
        if not path.endswith(".py") or is_test(path) or "print" not in line:
            return False
        code = tokens(line)  # print() called, never named in a comment or a string, never fingerprint()
        return any(
            name.type == tokenize.NAME and name.string == "print" and call.string == "("
            for name, call in pairwise(code)
        )
