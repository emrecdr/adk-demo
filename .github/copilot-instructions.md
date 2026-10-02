# Copilot instructions for this repository

This repository is a talk that teaches Google ADK (`google-adk[extensions]==2.9.2`, Python 3.13, `uv`) by building one
small git-branch code reviewer in seven phase folders, `phase_1_hello_world` … `phase_7_hardened`. `CLAUDE.md` at the
root is the long form of these instructions and `docs/ITERATION_MAP.md` the design record (§12 logs every decision
measured live); read the relevant section before changing a phase. Path-specific rules sit in `.github/instructions/`,
the recurring tasks in `.github/skills/`.

## Commands

- `uv sync` installs. `uv run ruff check . && uv run ruff format --check .` lints (`make lint`); `uv run pytest -q`
  runs the whole offline suite, no key needed (`make test`; `make ci` is both). Run both before calling anything done,
  and report what they printed.
- `uv run pytest -q tests/test_docs.py` after adding, removing or renaming any file; `-k phase_6` for one phase.
- `uv run python scripts/make_demo_repo.py` builds the demo repository the reviewer reviews (`--fix` commits its two
  fixes); `uv run python -m phase_7_hardened.review --head feature/payments --base main --profile gates-only` reviews
  it with no model call. Every other review command, `scripts/ask.py`, `scripts/rehearse.py` and `scripts/measure.py`
  call a provider: run them only when the task says so.

## Rules the tests enforce

- Each phase folder is a complete ADK agent folder, and phase N is a copy of phase N-1 plus one layer. Never extract
  shared modules and never import one phase from another. A fix to code several phases carry goes into the phase that
  introduced it and is then copied forward through every later phase that still carries the file; a change that is
  one phase's lesson stays in that phase. `git diff --no-index -- phase_3_changed_files phase_4_first_review` must
  read as exactly that phase's lesson.
- The docs are tested (`tests/test_docs.py`): `docs/ITERATION_MAP.md` §3 draws every file, so change the tree with
  the files; each phase README classifies every `*.py` directly in its folder against the previous phase, and the
  claims are checked against the bytes, so editing phase N can falsify phase N+1's `Unchanged:`. The grammar of both
  is in `.github/instructions/docs.instructions.md`.
- `root_agent.name` equals the folder name. Never name a sub-package module `agent.py`: ADK's nested loader would take
  it for an agent. `config.py` is the only file in a phase that names a provider (Gemini a plain model string, Copilot
  `LiteLlm("github_copilot/…")`); every change must work on both arms, and judging agents run at temperature zero.
- Phases 1–3 let provider errors surface on purpose: add no error hooks there. From phase 4 a provider error is the
  agent's own answer, and "did not look" must never read as "found nothing".
- Tools return a `{status: …}` dict and never raise at the model. Git runs by its full path from `PATH`, read-only
  verbs only, as an argv list with a timeout, inside `_environment(repo)`; nothing ever writes into the repository
  under review, and a failed git call raises `GitError`, never an empty answer.
- Every string a model reads is capped in characters with the cut named in the text. Every `subprocess.run` that
  decodes passes `encoding=`; no source spells `/tmp/` (`tempfile.gettempdir()`); a file a script or a fixture commits
  is written with `newline="\n"`.

## Tests

The suite is offline and lives in `tests/` alone; no test may call a provider or need a key. How a test is written —
the fixtures, the naming, async — is in `.github/instructions/tests.instructions.md`, which loads with any test.

## Secrets and configuration

One `.env` at the root (gitignored, copied from `.env.example`) holds `REVIEW_PROVIDER`, `REVIEW_MODEL` and the keys;
the shell wins over it at every entry point. Never read, print or quote `.env`, a key or the Copilot token.

## Style

Ruff, line length 120, Python 3.13. Comments and docstrings are plain prose that says why; commit subjects are
plain-prose sentences stating what changed and what was learned. A pull request comes with lint and the suite green
on the three platforms CI runs (`.github/workflows/ci.yml`, `azure-pipelines.yml`), and a workflow action is pinned
by its commit SHA.

## When reviewing a pull request

Flag a change that breaks a rule above or in `.github/instructions/`, naming the rule and the test that would catch
it — `tests/test_docs.py` for the README claims and the map's tree, `tests/test_layering.py` for phase 7's imports,
`tests/test_portability.py` for `encoding=` and `/tmp/` — and look first for the commonest miss: a file changed in one
phase and not carried forward, or carried where it was that phase's lesson.
