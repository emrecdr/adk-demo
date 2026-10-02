---
applyTo: "phase_*/**"
---

# Any phase folder

- Phases 1–3 keep `from . import agent` in `__init__.py`; from phase 4 the `__init__.py` imports nothing, because
  `python -m <phase>.review` imports the package before `main` reads `.env`, and `agent.py` builds its agents at
  import.
- Phases 6 and 7 export both `app` and `root_agent`: the loader prefers `app`, and a bare `root_agent` would lose the
  plugins. `build_app(chat=True)` is the chat graph with an intake agent, `chat=False` the command's over seeded
  state — two graphs, because `output_key` writes unconditionally.
- From phase 4, `on_model_error_callback` answers with a sentence and leaves `temp:failure` in state; reviewers and
  lanes carry a `before_agent_callback` that skips them when there is no evidence.
- State moves between agents via `output_key` and `{placeholder}`, `{key?}` where the key may be missing.
- A diff is read with `diff-tree -r -p` and `:(top,literal)` pathspecs, what lies inside a folder of that name
  excluded, under the merge base's attributes; `_git(..., ok=(0, 1))` is only for a call whose exit code 1 is an
  answer. A `GitError` becomes an error envelope only where envelopes are built (tools, preflight,
  `collect_evidence`), never an empty result.
- The reports of phases 6 and 7 cut each finding's evidence after the scrub, and break CI runners' command openers
  (`##[`, `##vso[`) and HTML comments' (`<!--`) in all they print.
