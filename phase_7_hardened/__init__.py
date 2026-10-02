"""Phase 7. The package answers `agent`, as the layout `adk create` scaffolds, without loading it.

Imported eagerly, as phases 1 to 3 do, the agent module brings the
model boundary in with the domain: measured, `import phase_7_hardened.core.findings`
loaded 187 `google.adk` modules through that one line and failed outright with
ADK absent — the one thing `core/` claims never to need. The attribute is
resolved on first use instead (PEP 562); `adk web` and `adk eval` find it as
before, and `tests/test_layering.py` imports `core/` with ADK absent.
"""

import importlib


def __getattr__(name: str):
    if name == "agent":
        return importlib.import_module(".agent", __name__)
    raise AttributeError(name)
