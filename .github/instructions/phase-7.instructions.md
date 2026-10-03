---
applyTo: "phase_7_hardened/**"
---

# Phase 7

- Layering is one way and tested (`tests/test_layering.py`): `core` → `rules` → `collect` → `judge` → `deliver`,
  imports relative and never spelled from the top (`phase_7_hardened.…`); `deliver/` imports `core` alone; `core/`
  and `rules/` must import with ADK absent and never import `google`, `litellm`, `subprocess`, `httpx`, `asyncio`,
  `os`, `socket`, `urllib`, `http` or `ssl`.
- A project rule is one self-contained class in `rules/`, one file a rule, found by discovery (a file named with a
  leading `_` is left aside: `rules/_template.py` is the copy-ready shape). Three kinds, one mental model — a line,
  a file, the tree: a `Rule` with `check(path, line) -> bool` over each added line; a `FileRule` with
  `check(file) -> list[tuple[int | None, str]]`, each `(line, what is wrong)`, over each changed file whole at the
  head (`file.lines`, `file.added`, `file.module`, `file.line(n)`); a `TreeRule` with `check(tree)` returning
  `(path, what)` or `(path, line, what)` over the head's paths and parsed modules (`tree.has`, `tree.module`,
  `tree.modules`, and `defined`, `classes`, `parameters` from `core/rules.py`). Each names `id` (kebab-case,
  unique), `severity` (`blocker`, `major` or `minor`), `title` and `fix` as class constants, and its expectations
  are constants in its file. `rules/no_print.py`, `rules/reviewer_instructions.py` and `rules/required_paths.py`
  are the three shapes, and `rules/README.md` the guide a rule's author reads first. A rule reads only what it is
  given and runs nothing. A rule's tests use `lines_hit` from `core/rules.py` and `self_check` from
  `rules/__init__.py`; `--list-rules` prints every check with its kind, its severity and its profiles, and
  `--check ID` runs one check alone.
- `config.toml` beside `review.py` is the one config file: `[review]` the flags' defaults, `[lint]` ruff's rules
  and what it ignores, `[profiles]` named lists of ids (`secrets`, `lint`, `lane.<name>` and the rules', or the
  groups `rules` and `lanes` for all of a kind). It is
  read whole, so a misspelt key is exit 2, and nothing is read from the repository under review, `.gitignore`
  included. A new rule runs in `default` without being named; add its id to `gates-only` by hand, and
  `tests/test_hardened.py` holds that list to every rule in the folder.
- `main` wraps the command: an error nothing else names is a sentence and exit 3, never Python's own exit 1, which
  would read as a blocker.
- The blast radius (`core/blast.py`) is parsed once from the head commit and shared with the tree rules; the lanes
  see it, the report leads with it, the verdict never reads it. Every count the report prints is a floor and says
  so; the tree is dropped from the evidence before the model calls.
- Every untrusted section a lane or a verifier reads goes through `fenced(label, placeholder)` in `judge/lanes.py`:
  two marker lines carrying `BOUNDARY`, a nonce drawn once a process, and the instruction ends with `REMINDER`.
  Never escape or rewrite the content itself: a lane quotes the diff verbatim, and grounding holds the quote to the
  real lines.
