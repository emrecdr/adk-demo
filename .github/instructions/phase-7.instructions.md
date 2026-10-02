---
applyTo: "phase_7_hardened/**"
---

# Phase 7

- Layering is one way and tested (`tests/test_layering.py`): `core` → `rules` → `collect` → `judge` → `deliver`,
  imports relative and never spelled from the top (`phase_7_hardened.…`); `deliver/` imports `core` alone; `core/`
  and `rules/` must import with ADK absent and never import `google`, `litellm`, `subprocess`, `httpx`, `asyncio`,
  `os`, `socket`, `urllib`, `http` or `ssl`.
- A project rule is one self-contained class in `rules/`, one file a rule, found by discovery: a `Rule` with
  `check(path, line) -> bool` over each added line, or a `TreeRule` with `check(tree) -> list[tuple[str, str]]`,
  each `(path, what is wrong)`, over the head's paths and parsed modules (`tree.has`, `tree.module`,
  `tree.modules`, and `defined`, `classes`, `parameters` from `core/rules.py`). Each names `id` (kebab-case,
  unique), `severity` (`blocker`, `major` or `minor`), `title` and `fix` as class constants, and its expectations
  are constants in its file. `rules/no_print.py` and `rules/required_paths.py` are the two shapes. A rule reads
  only what it is given and runs nothing.
- `config.toml` beside `review.py` is the one config file: `[review]` the flags' defaults, `[lint]` ruff's rules
  and what it ignores, `[profiles]` named lists of ids (`secrets`, `lint`, `lane.<name>` and the rules'). It is
  read whole, so a misspelt key is exit 2, and nothing is read from the repository under review, `.gitignore`
  included. A new rule runs in `default` without being named; add its id to `gates-only` by hand, and
  `tests/test_hardened.py` holds that list to every rule in the folder.
- `main` wraps the command: an error nothing else names is a sentence and exit 3, never Python's own exit 1, which
  would read as a blocker.
- The blast radius (`core/blast.py`) is parsed once from the head commit and shared with the tree rules; the lanes
  see it, the report leads with it, the verdict never reads it. Every count the report prints is a floor and says
  so; the tree is dropped from the evidence before the model calls.
