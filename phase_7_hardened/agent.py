"""The loader's entry point: `adk web .` and `adk run` look here for `app` and `root_agent`.

The chat-shaped App is built here and only here, because only the loader
wants it: the driver builds the lanes-only shape itself, after the readiness
check, and nothing but the loader imports this file. Measured with the build
in `judge/graph.py` instead, where every import of the package reached it:
each start built five agents it would not run, the Copilot arm loaded ADK's
LiteLLM wrapper for them — 150 ms before `--help` printed — and a provider
misspelled in the shell was a traceback at import, exit 1, in place of
`require_ready`'s sentence and exit 2.
"""

from .judge.graph import build_app

app = build_app(chat=True)
root_agent = app.root_agent
