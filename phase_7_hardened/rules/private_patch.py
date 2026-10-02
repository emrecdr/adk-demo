"""A project's own rule: a test that patches a private name is tied to an implementation, not to a behaviour."""

from __future__ import annotations

import re

from ..core.blast import is_test
from ..core.rules import Rule

#: A patch call and its arguments: patch(...), patch.object(...), mocker.patch(...), monkeypatch.setattr(...).
_PATCH = re.compile(r"\b(?:patch(?:\.object)?|setattr)\(([^)]*)")
#: A string argument naming what is patched: a dotted path, or an attribute name alone.
_NAME = re.compile(r"""["']([A-Za-z_][\w.]*)["']""")


class PrivatePatch(Rule):
    """A name with one leading underscore is the module's own business: a test that patches it fails when the
    implementation is refactored with its behaviour unchanged. A dunder name is public by convention."""

    id = "private-patch"
    severity = "minor"
    title = "a test patches a private name"
    fix = "Patch the public boundary the unit depends on, or pass the collaborator in."

    def check(self, path: str, line: str) -> bool:
        if not path.endswith(".py") or not is_test(path) or (call := _PATCH.search(line)) is None:
            return False
        leaves = (name.rsplit(".", 1)[-1] for name in _NAME.findall(call.group(1)))
        return any(leaf.startswith("_") and not leaf.startswith("__") for leaf in leaves)
