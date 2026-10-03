# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A talk that teaches Google ADK (pinned `google-adk[extensions]==2.9.2`, Python 3.13, `uv`) by building one small git-branch code reviewer in seven phase folders. `docs/ITERATION_MAP.md` is the design record: per-phase goals, the reasoning behind every choice, and (§12) a log of decisions measured live. Read the relevant section before changing a phase. Each `phase_*/README.md` is the script for that step.

## Commands

```bash
uv sync                                    # install (make sync)
uv run pytest -q                           # full offline suite, no key needed (make test)
uv run pytest -q tests/test_reviewer.py    # one file
uv run pytest -q tests/test_docs.py::test_the_maps_tree_draws_every_file_in_the_working_tree_and_nothing_else
uv run pytest -q -k phase_6                # tests parametrized over one phase
uv run ruff check . && uv run ruff format --check .   # lint (make lint); `make format` fixes; `make ci` = lint + test

uv run python scripts/make_demo_repo.py          # build <tmp>/adk-demo-repo: main + feature/payments with 4 planted defects
uv run python scripts/make_demo_repo.py --fix    # commit the two fixes on feature/payments
uv run adk web .                                 # browser UI, every phase in one dropdown
uv run adk run phase_2_preflight                 # terminal chat with one phase
uv run python scripts/ask.py <phase> "message"   # one headless turn through any phase; exit 3 when an error escapes the engine (from phase 4 a failed agent's hook answers, exit 0)
uv run python -m phase_6_reviewer.review [repo] --head feature/payments [--base main] [--fail-on …]
uv run python -m phase_7_hardened.review [repo] [--head B] [--base main | --all] [--path DIR] [--fail-on …] [--verify | --no-verify] [--max-tokens N] [--profile NAME | --check ID] [--dry-run] [--list-rules]
uv run python -m phase_7_hardened.review --head feature/payments --base main --profile gates-only   # the demo reviewed by code alone: the gates and every rule, no model call, no key
uv run python -m phase_7_hardened.review --head feature/payments --base main --dry-run   # what a review would cover and run — revisions, files, profile, model, readiness — and nothing run
uv run python scripts/rehearse.py --dry-run      # every phase's demo line in order; --pause 65 for the free tier
uv run python scripts/measure.py --runs 5 [--all] # live: per planted defect, how often a lane names it (--all: as a whole project)
git diff --no-index -- phase_3_changed_files phase_4_first_review   # one phase's lesson (make diff FROM=… TO=…)
```

`review.py` exists from phase 4 on; with no `repo` it reviews the demo repository. Exit codes: 0 approved (phase 4: judged, whatever it found), 1 a blocker (phase 5: the verdict said REQUEST CHANGES; phase 4 never exits 1), 2 a usage error before any model call (from phase 6 also an arm that is not ready, or a branch that adds nothing: "no change to review"; in phase 7 also a `config.toml`, profile or rule file that cannot run, nothing under `--path`, or no choice made at the question asked when neither `--base` nor `--all` is given), 3 a hole: an agent, lane, gate or rule failed, or a rule could not look (the head's tree not listed, or a file it holds not read whole), or (from phase 6) a changed file no lane read whole — binary, a submodule, cut at the diff cap, or (phase 7) past the lanes' block cap — named under "not read", or a finding at the `--fail-on` bar whose quote the diff does not bear out; and from phase 4, any error nothing else names (`main` wraps the command: a sentence, never Python's own exit 1, which would read as a blocker).

## Configuration

One `.env` at the root (copy `.env.example`) serves every phase. `REVIEW_PROVIDER=copilot|gemini` picks the arm, `copilot` when unset; `REVIEW_MODEL` blank means `gpt-4.1` / `gemini-2.5-flash`. Copilot needs a one-time `uv run python scripts/copilot_login.py`; Gemini needs `GOOGLE_API_KEY`. Copilot is the first-class arm: the talk is given on it and the team uses it, so live measurements and rehearsals run there first. Phase 7 also reads `REVIEW_VERIFIER_MODEL` and `REVIEW_FALLBACK_MODEL`.

The shell wins over `.env` at every entry point: ADK 2.9.2 restores the variables set before it loads the file, and the `review.py` commands and `scripts/ask.py` load it without overriding. The phase 6 and 7 reports name the model and arm that ran.

## Architecture

**Each phase folder is a complete, standalone ADK agent folder, and phase N is a copy of phase N-1 plus one layer.** Duplication across folders is deliberate: only `.env` is shared, no phase imports another, and a `git diff --no-index` between neighbouring folders must be exactly that phase's lesson. Do not extract shared modules. A fix to code that several phases carry belongs in the phase that introduced it and is then carried forward through the later copies; a change that is one phase's lesson stays in that phase (ITERATION_MAP §12, "Phase 6 after phase 7's reviews").

The progression: 1 a bare `Agent` → 2 a read-only git tool → 3 more tools, `ToolContext.state`, a `before_tool_callback` path guardrail → 4 a `Workflow` (collector → reviewer with `output_schema`) plus a CLI → 5 fan-out to three lanes (security, tests, complexity) + `JoinNode` + a verdict agent → 6 evidence gathered in Python first, lanes only judge, code decides the verdict, `App` with plugins → 7 phase 6 regrouped by dependency direction plus retries, a token ceiling, a ruff gate, a `--verify` second opinion, and each changed file's blast radius (`core/blast.py`: an import graph parsed from the head commit, shown to the lanes as `{blast?}` and heading the report, never read by the verdict), fences around every untrusted section the lanes and verifiers read (`judge/lanes.py`: two marker lines carrying a nonce drawn once a process, a reminder after them, the content never escaped so a quote still grounds), and a project's own rules (`rules/`: one self-contained class a file, of three kinds — a `Rule`, `check(path, line)` over each added line; a `FileRule`, `check(file)` over each changed file whole at the head, its lines, the lines the change added and its module; a `TreeRule`, `check(tree)` over the head's paths and parsed modules, naming a line where it knows one — `rules/_template.py` the copy-ready shape discovery leaves aside and `rules/README.md` the guide, `lines_hit` and `self_check` a rule's first tests, `--list-rules` every check with its kind and its profiles, `--check ID` one check alone; phase 7's one config file, `config.toml` beside `review.py`, holds the profiles under `[profiles]`, named lists of rule ids with the built-in checks `secrets`, `lint`, `lane.<name>` among them and the groups `rules` and `lanes` for all of a kind, and the review policy (`[review]` `fail_on`, `max_tokens`, `verify`, each a flag's default; `[lint]` ruff's `rules` and `ignore`, which only the file sets), read whole so a misspelt key is exit 2; with no `--profile`, `default` runs every check and every rule in the folder; `--profile` is the only choice, and nothing is read from the repository under review, `.gitignore` included: git keeps ignored files out of commits), and what a review covers (`--path DIR` a folder of the change, the rest counted in the report; `--all` every file at the head, diffed against git's empty tree; `--head` defaults to the branch checked out; with neither `--base` nor `--all` a terminal asks, and a pipeline reviews the change against `main`, or `master`).

Load-bearing rules the tests enforce:

- **Loader.** `root_agent.name` must equal the folder name. `adk web` uses ADK's *nested* loader, which treats any folder holding an `agent.py` (up to five levels deep) as an agent, so never name a sub-package module `agent.py` (phase 7's graph lives in `judge/graph.py` for this reason). `test_wiring.py` asserts `adk web` lists exactly the phases.
- **Package roots.** Phases 1–3 keep the scaffold's `from . import agent`. From phase 4, `__init__.py` imports nothing, because `python -m <phase>.review` imports the package before `main` reads `.env`, and `agent.py` builds its agents at import. Phase 7's root answers `agent` lazily via PEP 562 `__getattr__`.
- **Providers.** `config.py` is the only file in a phase that names a provider: Gemini is a plain model string, Copilot is `LiteLlm("github_copilot/…")`. Every change must work on both arms. Judging agents run at temperature zero.
- **Phase 6/7 shape.** `agent.py` exports both `app` and `root_agent` (the loader prefers `app`, and a bare `root_agent` would lose the plugins). `build_app(chat=True)` adds an intake agent for chat; the CLI uses `chat=False` over seeded state. They are two graphs because `output_key` writes unconditionally. Plugins: `RedactSecretsPlugin`, `UsageLedger`, `ReportProviderErrors`.
- **Phase 7 layering** (`tests/test_layering.py`): `core` → `rules` → `collect` → `judge` → `deliver`, with imports pointing one way only, never spelled from the top (`phase_7_hardened.…`), and `deliver/` importing `core` alone. `core/` and `rules/` may not import `google`, `litellm`, `subprocess`, `httpx`, `asyncio`, `os`, `socket`, `urllib`, `http` or `ssl`, and must import with ADK absent.
- **Error handling starts at phase 4 on purpose.** Phases 1–3 deliberately let provider errors surface as tracebacks, so do not add hooks there. From phase 4, `on_model_error_callback` turns a provider error into the agent's answer and leaves `temp:failure` in state; reviewers and lanes carry a `before_agent_callback` that skips them when there is no evidence. "Did not look" must never read as "found nothing".

Conventions kept across phases:

- Tools return a `{status: …}` dict and never raise at the model.
- Git runs by its full path from `PATH`, never from the current directory (Windows searches it first, and it can be the checkout under review), as an argv list with a timeout that stops the whole command (Git for Windows' `git.exe` starts the real git as its child), read-only verbs only, and nothing ever writes into the repository under review, not even the lazy fetch a partial clone would make; every call runs in `_environment(repo)`: no inherited `GIT_*` variable, no global or system config and no attributes file but the repository's (`GIT_CONFIG_GLOBAL`/`GIT_CONFIG_NOSYSTEM`, `core.attributesFile` set to the null device), `safe.directory` for the one repository named, no lazy fetch, no replace refs or grafts, `core.precomposeUnicode` and `diff.suppressBlankEmpty` fixed through `GIT_CONFIG_COUNT`. A file's diff is read as git prints it for no one's settings, through plumbing (`diff-tree -r -p`, which reads none of the repository's display settings): each path as `:(top,literal)` pathspec magic with what lies inside a folder of that name excluded (`:(top,exclude,glob)<name>/**`, never the entry, so a submodule stays; `top`, because without it Git for Windows reads a `\` in a name as a separator), the merge base's attributes (`--attr-source`, git 2.41; under phase 7's `--all`, the empty tree's, so none), `--no-color --no-ext-diff --no-textconv`. Under `--all` every file is added, so one call reads them all, split at each `diff --git` line (`whole_diffs`). A call that fails, cannot start (no git on `PATH`) or runs past its timeout raises `GitError`, turned into an error envelope only where envelopes are built (tools, preflight, `collect_evidence`); never answer it as an empty result, because several helpers read git's output without its exit code. `_git(..., ok=(0, 1))` is only for calls whose exit code 1 is an answer (`rev-parse --verify`, `merge-base`, phase 7's `symbolic-ref --quiet`).
- Every string a model reads is capped in characters, with the cut named in the text (phase 7 also caps the lanes' whole block of diffs and the blast radius beside it); the report of phases 6 and 7 cuts each finding's evidence the same way, after the scrub, and breaks CI runners' command openers (`##[`, `##vso[`) and HTML comments' (`<!--`) in all they print.
- State moves between agents via `output_key` and `{placeholder}` (use `{key?}` where the key may be missing).
- Every `subprocess.run` that decodes passes `encoding=` (`_git` and the blast radius read bytes and decode UTF-8 themselves), and no source under `phase_*` or `scripts/` spells `/tmp/` (use `tempfile.gettempdir()`). `test_portability.py` enforces both for Windows. Every file a script or a fixture commits is written with `newline="\n"`, a `.env` that is not UTF-8 is a sentence and exit 2, and `.github/workflows/ci.yml` and `azure-pipelines.yml` run lint and the suite on Windows, Linux and macOS.

## Tests

The suite is fully offline. `tests/conftest.py` registers a `FakeModel` in ADK's `LLMRegistry` for `fake.*`. `load_phase(monkeypatch, phase)` sets `REVIEW_MODEL=fake` and re-imports the phase fresh, so the real `build_model()`, Runner, `Workflow`, callbacks and plugins all run. The fake answers whatever canned payload the request's response schema accepts, or a sentence when there is no schema. The `fake_provider` fixture's `raises_when(text, exc)` / `answers_when(text, payload)` key on text in the system instruction, to simulate a provider failing or a verifier refuting. `demo_repo` is a session-scoped real repository from `make_demo_repo.build`. `asyncio_mode = "strict"`, so async tests need `@pytest.mark.asyncio`. Tests live only in `tests/`, never inside phase folders.

## The docs are tested, so update them with the code

`tests/test_docs.py` reads the docs the way a reader does:

- The tree in `docs/ITERATION_MAP.md` §3 must draw **every** tracked or untracked-but-not-ignored file, and nothing else (`uv.lock` and `.gitignore` are exempt). Adding, removing or renaming any file, a scratch file included, fails the suite until the tree is updated.
- Each phase README must classify every `*.py` directly in its folder as `New:`, `Changed:` or `Unchanged:` (or `Gone:`/`Moved:`) relative to the previous phase, as a sentence of backticked names ending in a period. The claims are checked against the bytes, so editing a file in phase N can falsify phase N+1's `Unchanged:` claim.
- ITERATION_MAP needs a `## <section>. Phase <n> — ` section per phase folder.

The docs state no static counts of the repository's current state — how many tests, how long the suite takes, how many flags or example runs — since routine work makes each one stale. A measured number, as ITERATION_MAP §12 records it, is history and stays. The docs carry no dates either: none of them is a changelog.

## Copilot's files

`.github/copilot-instructions.md` is the short form of this file for GitHub Copilot, with path-specific rules in `.github/instructions/`, skills for the recurring tasks in `.github/skills/`, a custom agent in `.github/agents/` and the cloud agent's setup in `.github/workflows/copilot-setup-steps.yml`. A rule that changes here changes there too; `tests/test_copilot.py` holds those files to their format, and `tests/test_docs.py` holds every guide, this file included, to the paths it names.

## History

The published history starts from one commit; a phase's lesson is the diff between neighbouring folders, not a commit. Commit subjects are plain-prose sentences stating what changed and what was learned. Decisions measured against live providers are recorded in ITERATION_MAP §12.
