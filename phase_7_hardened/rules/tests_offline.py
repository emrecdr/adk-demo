"""A project's own rule: a test that reaches the network is slow, flaky and leaks data; fake it at the boundary."""

from __future__ import annotations

import re

from ..core.blast import is_test
from ..core.rules import Rule

#: A call that opens a connection, through the libraries a test is likeliest to reach for. A client built is no
#: connection opened: `httpx.Client(transport=MockTransport(...))` is the fake this rule asks for.
_NETWORK = re.compile(
    r"\b(?:requests|httpx|urllib\.request|aiohttp|socket)\."
    r"(?:get|post|put|delete|patch|head|options|request|urlopen|create_connection|socket)\("
)


class OfflineTests(Rule):
    """The suite that proves this reviewer runs offline, on a fake model; a project's tests should too. A fake at
    the boundary, a stub client or a recorded answer, keeps a test fast, repeatable and private."""

    id = "tests-offline"
    severity = "major"
    title = "a test reaches the network"
    fix = "Fake the network at the boundary: a stub client or a recorded answer, never a live call."

    def check(self, path: str, line: str) -> bool:
        return path.endswith(".py") and is_test(path) and _NETWORK.search(line) is not None
