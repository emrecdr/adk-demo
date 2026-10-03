# ADK by iteration — a code reviewer in six phases and an optional seventh

This repository is a talk. It introduces Google ADK (2.9.2) by building one
thing in six steps: a small code reviewer that takes a git repository and two
branches, reads what the branch changed, has three specialised model
reviewers judge it, finds hard-coded secrets by code, and decides a verdict
and an exit code that a build can act on. Every step is a folder you can run
on its own, and every step runs on GitHub Copilot, the arm the talk is given
on, and on Gemini. A seventh,
optional phase regroups the result by dependency direction and hardens it.

The talk's slides are in `docs/presentation/`: the PDF, and the PPTX with and
without the speaker notes, each in the deck's fonts and in basic fonts (Arial,
Courier New) for a machine that lacks them.

Working with an assistant: `CLAUDE.md` is the guide for Claude Code, and
`.github/` holds Copilot's.

What ADK adds over a single agent file, where one prompt sets every step: it
lets code control the whole process, so every run takes the same steps in the
same order, every step can be observed, and a model's judgement is used
exactly where it is needed.

## What we built

By phase 6, `uv run python -m phase_6_reviewer.review --head feature/payments`
does this, in this order:

1. **Evidence, by code.** Read-only git resolves both branches and their
   merge base, lists the changed files and takes every file's diff. No model
   has been called yet.
2. **A gate, by code.** Every added line is scanned for known credential
   shapes; a hit is a blocker with an exact file and line, and the same
   shapes are redacted from everything a model will see.
3. **Judgement, by models.** Three lanes — security, tests, complexity —
   review the same diff at once, each returning typed findings that must
   quote the diff.
4. **A verdict, by code.** Findings that do not quote whole lines of their
   own file's diff are dropped and counted, duplicates across lanes are
   folded, a failed lane is named with its reason, and the exit code
   follows: 0 approved, 1 a blocker, 2 a usage error, 3 a hole: a lane that
   failed, a file no lane read whole, a finding at the bar no quote bears
   out, or an error nothing else names, which never reads as a blocker.
5. **A report** that a person reads in a terminal, ending with what the run
   cost.

In `adk web` a second graph answers a chat message: an intake agent
gathers the diff through the tools, the same lanes judge under the same
plugins, and a verdict agent writes the verdict, so there it is a model's.

Phase 7, for those who want more, keeps that command and regroups it by
dependency direction — `core/`, `rules/`, `collect/`, `judge/`, `deliver/`,
with a test that keeps every import pointing one way — and adds retries on
both arms, a token ceiling, a second gate, a second opinion, each changed
file's blast radius, and a project's own rules, chosen by profile; it also
reviews one folder of a change, or every file at the head.

## How we built it

- **One folder per phase, each a complete ADK agent folder.** Phase N is a
  copy of phase N-1 plus one layer, so `git diff --no-index` between two
  folders is exactly that phase's lesson, and any folder can be opened, read
  and run alone. Every folder carries a `README.md` saying what it does,
  what changed since the previous phase, how to run it, and what to notice.
- **Both providers from the first line.** `REVIEW_PROVIDER` in one central
  `.env` picks Gemini or Copilot; `config.py` is the only file in any phase
  that names a provider, and nothing else knows which arm it is on.
- **Conventions introduced once and kept.** A tool returns a
  `{status: …}` dict and never raises at the model. Git runs as an argv list
  with a timeout, a failed or timed-out call a named error and never an
  empty answer, read verbs only, and nothing ever writes into the
  repository under review. Every string a model reads is capped in
  characters with the cut named. State moves between agents through
  `output_key` and `{placeholder}` interpolation. Graph shapes are
  `Workflow` edges and `JoinNode`; cross-cutting policy lives in `App`
  plugins.
- **Tested offline, verified live.** A fake model registered with ADK's own
  model registry drives every phase through the real engine, so the tests
  need no key. The Copilot arm has been run live end to end; the Gemini arm
  needs only a key.
- **A generated repository to review.** `scripts/make_demo_repo.py` builds a
  throwaway repository with a `main` branch and a `feature/payments` branch
  carrying four planted defects, and `--fix` commits the two fixes, so the
  demo is rehearsable and never waits on a real branch.

## The phases

| Phase | What we do in it | What ADK teaches |
|---|---|---|
| [1 — hello world](phase_1_hello_world/README.md) | The smallest legal agent: a model, a name, an instruction. Run it, then flip the provider and run it again; only the model name in the event's Request view changes. | `Agent`, `root_agent`, the agent folder, `adk web` and `adk run`, one `.env` for every phase |
| [2 — preflight](phase_2_preflight/README.md) | The agent takes a repository and two branches and proves they exist with one read-only git tool, answering with a fixed preflight block. | A function tool from a signature and docstring; the status envelope; `output_key` |
| [3 — changed files](phase_3_changed_files/README.md) | Two more tools list the change and show one file's diff. The first phase that treats a tool argument as hostile: a diff path must be one the change touched. | `ToolContext.state` as the boundary between tools; `before_tool_callback`; named caps |
| [4 — the first review](phase_4_first_review/README.md) | Gathering and judging become two agents on one edge; the reviewer returns typed findings that must quote the diff. The folder is also a command: arguments in, the typed review out, an exit code. | `Workflow`, `output_schema`, `{placeholder}` from state, `include_contents`, temperature zero, a model-error hook, the `InMemoryRunner` behind a command |
| [5 — parallel lanes](phase_5_parallel_lanes/README.md) | The reviewer becomes three lanes from a table, judging at once; a join waits; a verdict agent writes them up. The provider is still the only arm-specific code. Its command relays the verdict's word as the exit code. | Fan-out and `JoinNode`, `max_concurrency`, a planner where the provider has one |
| [6 — the reviewer](phase_6_reviewer/README.md) | The command a team can trust: evidence by code, lanes judge, code decides, with a secrets gate, three plugins and exit codes. Chat still works. | `App` and plugins, the model-error hook as a plugin, request deadlines on both arms |
| [7 — hardened](phase_7_hardened/README.md) | Optional, for advanced users. Phase 6 regrouped into `core/`, `rules/`, `collect/`, `judge/`, `deliver/` with a layering test, plus retries on both arms from one request config, a token ceiling that wraps up, a ruff gate, a second opinion on each lane finding a gate has not already made, each changed file's blast radius, read from the syntax tree, a project's own rules grouped into profiles, and what a review covers: one folder of the change, or every file at the head. | Ports and adapters in miniature, client retries set on the request, a ceiling through plugin hooks, a second graph fanned out per finding, a model per role, a package root that answers `agent` without loading it, a blast radius read from the syntax tree, rules as classes a profile chooses, the whole project as a change against git's empty tree |

Each phase's README is the script for that step. The design record, with
the reasoning behind every choice and a presenter's checklist, is
[`docs/ITERATION_MAP.md`](docs/ITERATION_MAP.md).

## Prerequisites

- `git` 2.41 or later and [`uv`](https://docs.astral.sh/uv/) on `PATH`. Python 3.13 is the
  project's requirement; `uv sync` fetches it if the machine has none.
- For the Copilot arm, the one the talk runs on, a GitHub account with
  Copilot; no key, a one-time device login instead. For the Gemini arm, an
  AI Studio API key.
- macOS, Linux and Windows are all fine; see the Windows notes below.

## Install

```bash
git clone <this repository>
cd adk_review_demo
uv sync                          # the virtual environment, ADK 2.9.2 and everything else, pinned by uv.lock
```

## Configure

```bash
cp .env.example .env             # one file at the root; every phase reads it
chmod 600 .env                   # it holds a key: readable by you alone
```

Edit `.env`:

- `REVIEW_PROVIDER=copilot` or `gemini`. The talk is given on Copilot and
  the team runs on it, so it is also the arm when none is named; Gemini is
  the other arm. Every phase works on both.
- `GOOGLE_API_KEY=…` for the Gemini arm.
- `REVIEW_MODEL=` blank for the provider's default (`gpt-4.1` or
  `gemini-2.5-flash`), or a model name to override it.
- `REVIEW_VERIFIER_MODEL=` (phase 7 only) a model of its own for the second
  opinion; blank means `REVIEW_MODEL`.
- `REVIEW_FALLBACK_MODEL=` (phase 7 only) a second model behind every role's
  first: ADK's `FallbackModel` moves a call to it on a 429 or a 5xx, each
  model tried once. On the free tier the quota is per model, so a second
  model is a second quota. Blank means none.

For the Copilot arm, log in once; the token is cached and reused:

```bash
uv run python scripts/copilot_login.py            # GitHub device flow: open the URL, enter the code
```

The login keeps the token's folder readable by you alone (on Windows,
your user profile's permissions do), and it, like phases 6
and 7, takes an empty token file for none. A debug log (`adk web -v`)
of phases 6 and 7 never shows the token: they hide it from LiteLLM's log
lines; phases 1 to 5 do not, so keep `-v` off a shared screen there.
`adk web` keeps each chat in the phase's `.adk/session.db`, the diffs it
read included; delete the folder when a chat is done with.

## Run

Build the repository the demo reviews, then run any phase:

```bash
uv run python scripts/make_demo_repo.py           # <demo repo>: main + feature/payments, four planted defects

uv run adk web .                                  # the browser UI; every phase in one dropdown
uv run adk run phase_2_preflight                  # terminal chat with one phase
uv run python scripts/ask.py phase_3_changed_files "what did feature/payments change in <demo repo>?"
```

`<demo repo>` is the path `make_demo_repo.py` prints: `adk-demo-repo` in the
platform's temp directory. The message every phase from 2 on wants is:

```
review <demo repo>, branch feature/payments against main
```

From phase 4 on, every phase is also a command: the repository and both
branches on the command line, the answer on stdout, an exit code. With no
path it reviews the demo repository.

```bash
uv run python -m phase_4_first_review.review --head feature/payments     # the typed review as JSON; exit 0
uv run python -m phase_5_parallel_lanes.review --head feature/payments   # the verdict; exit 1 on REQUEST CHANGES
```

Phase 6's exit code is the verdict, decided in code:

```bash
uv run python -m phase_6_reviewer.review --head feature/payments   # exit 1: blockers, the key pair and the shell
uv run python scripts/make_demo_repo.py --fix                        # commit the two fixes on the branch
uv run python -m phase_6_reviewer.review --head feature/payments   # exit 0; majors stay in the report for a person
uv run python -m phase_6_reviewer.review /path/to/any/repo --base main --head my-branch
```

Phase 7 is the same command with `--verify`, `--max-tokens N`,
`--profile NAME`, `--check ID`, `--path DIR`, `--all`, `--dry-run` and `--list-rules` added, and `--head`
the branch checked out when not named; its README shows a run of each. With neither
`--base` nor `--all`, a person at a terminal is asked which, and a
pipeline reviews the change against `main`, or `master`. A pipeline checks
out a detached commit, and one commit deep unless told otherwise (GitHub
Actions and Azure Pipelines alike), so name `--head` there and fetch the base
branch with its history, or review the whole head with `--all`. The defaults of
`--fail-on`, `--max-tokens` and `--verify`, ruff's rules and what it ignores, and the
profiles live in one file, `phase_7_hardened/config.toml`; a flag
overrides its setting for one run, and with no `--profile` a review runs
`default`, every check.

To rehearse the whole talk, every phase's demo line in order and then the
fix-and-rerun moment, each its own process, with a summary of exit codes at
the end:

```bash
uv run python scripts/rehearse.py --pause 65     # the pause is a free-tier minute; 0 on a billed key or Copilot
uv run python scripts/rehearse.py --dry-run      # just print the commands
uv run python scripts/measure.py --runs 5        # per planted defect, in how many runs a lane named it; --all as a whole project
```

To see one phase's lesson as a diff:

```bash
git diff --no-index -- phase_3_changed_files phase_4_first_review
```

It is cleanest on a fresh checkout, before any `__pycache__` exists.
`make help` lists most of them as targets, for those who like `make`: phase
7's flags go through `ARGS=` (`BASE= ARGS=--all` for the whole project), and
`make rehearse` only prints the steps; nothing needs it.

## Test and lint

```bash
uv run pytest -q                                      # offline, no key needed; a few tests run on Windows alone
uv run ruff check . && uv run ruff format --check .   # lint and formatting
```

The tests load every phase the way `adk web` does, build the model on both
arms, and drive each graph through the real engine with a fake model
registered in ADK's model registry: the git tools against a real repository,
the guardrail, the typed review landing in state, the three-lane fan-out, the
plugins, the phase 4 and 5 commands' exit codes, the phase 6 command end to end (exit 1 on the planted branch, exit 2
on a wrong branch, exit 3 with the lane named and the rest still reported
when a provider call fails), phase 7's additions and its layering (every
import points one way, the core runs nothing and imports with ADK absent), and the docs: the folder tree
in the design record matches the working tree, and every phase README's file
claims match the bytes. Live answers need the key or the Copilot token.

## Windows

Every command above runs on Windows 10 and 11 with Git for Windows (2.41
or later, on `PATH`) and `uv`, and the whole offline suite runs on Windows,
Linux and macOS on every push: `.github/workflows/ci.yml` on GitHub,
`azure-pipelines.yml` on Azure DevOps. PowerShell 7 takes the commands as
written. What differs:

- **A variable for one command.** `REVIEW_PROVIDER=gemini uv run …` is a
  POSIX shell's. In PowerShell, `$env:REVIEW_PROVIDER = "gemini"` first and
  `Remove-Item Env:REVIEW_PROVIDER` after; in cmd, `set REVIEW_PROVIDER=gemini`.
- **The exit code.** `echo $?` prints `True` or `False` in PowerShell: use
  `$LASTEXITCODE`, or `echo %ERRORLEVEL%` in cmd.
- **Chaining and comments.** Windows PowerShell 5.1, the one Windows ships,
  refuses `&&`: run the commands one by one, or use PowerShell 7. cmd reads
  a trailing `# comment` as arguments and keeps `'…'` quotes as part of the
  text: leave the comment off there, and quote with `"…"`.
- **Files and folders.** `copy .env.example .env` for `cp`. The demo
  repository is `$env:TEMP\adk-demo-repo` (`%TEMP%\adk-demo-repo` in cmd),
  and a terminal or an editor holding it open stops the rebuild, which says
  so. `chmod 600 .env` has no counterpart: your user profile's permissions
  keep `.env`, and the Copilot token, yours.
- **`.env` is UTF-8.** Windows PowerShell 5.1's `>` and `Out-File` write
  UTF-16: save it from an editor, or with `Set-Content -Encoding utf8`. A
  command given one says so and exits 2.
- **A report saved to a file.** The report is printed as UTF-8, so a
  code-page console shows it; Windows PowerShell 5.1 re-encodes what `>`
  redirects, so run `[Console]::OutputEncoding = [Text.UTF8Encoding]::new()`
  first, or use PowerShell 7.4 or later.
- **`adk web`** turns its auto-reload off on Windows, with a warning;
  `uv run adk web --no-reload .` starts without it.

What the code does for Windows, pinned by `tests/test_portability.py`,
`tests/test_git_tools.py` and, for the lint gate, `tests/test_hardened.py`: git runs by its full path from `PATH`, never from
the current directory, which Windows searches first and which can be the
checkout under review; a git past its timeout is stopped with the real git
that Git for Windows' `git.exe` starts; a path reaches git from the top
(`:(top,literal)`), so a `\` in a file's name stays part of it; the lint
gate writes each file under a name of its own, so a branch's `nul.py` or
`a:b.py` is linted like any other; git's output is decoded as UTF-8, every
file a script commits is written with `\n`, and nothing in the phases
spells a POSIX path.

## Repository layout

```
.env, .env.example      the one configuration file, shared by every phase
phase_1_hello_world/    one agent folder per phase, each complete on its own
… phase_7_hardened/     (agent.py, config.py, tools.py, … and a README.md each; phase 7 is grouped into core/, rules/, collect/, judge/, deliver/)
scripts/                make_demo_repo.py, ask.py, rehearse.py, measure.py, copilot_login.py
tests/                  the offline suite
docs/ITERATION_MAP.md   the design record and the presenter's checklist
Makefile                optional shortcuts over the same uv commands
```

## Troubleshooting

- **`review: REVIEW_PROVIDER=gemini needs GOOGLE_API_KEY`** (phases 6 and 7,
  exit 2): fill the key in `.env`, or switch the arm. Phases 4 and 5 check
  nothing first: their first call fails, named, exit 3.
- **`review: git diff-tree did not answer within 30 s`** (exit 2; `diff-tree`
  from phase 6, where the command reads the diffs), or any other git verb: git was stopped at its timeout — a very large change, a slow
  disk, a repository another process holds — and nothing was reviewed. In
  chat the tool answers the same sentence. On phase 7, ruff past its own
  timeout is `gate_lint — FAILED: ruff did not answer within 60 s`, exit 3.
- **`review: base branch 'main' is ambiguous: refs/heads/main and
  refs/tags/main; name one in full`** (exit 2): a tag, often one fetched
  from a fork, has a branch's name, and git would take the tag. Pass the
  full name, `--base refs/heads/main`.
- **`review: 'my-branch' adds nothing to 'main': no change to review`**
  (exit 2, phases 6 and 7): the branch is already merged, or names the
  same commit as the base. Nothing was reviewed, so nothing is approved.
- **``- not read `path`: …`` under a `DEGRADED` verdict** (exit 3, phases 6
  and 7): no lane read that file whole — it is binary, a submodule whose
  commits are another repository's, or its diff is past
  the 4,000-character cap and the lanes read only its start, or, in phase
  7, it fell past the 250,000 characters the lanes read in all. The gates
  still read the whole diff. Split the change, narrow it with `--path`, or
  review the file by hand.
- **`review: 'main' and 'my-branch' share no history: no change to review`**
  (exit 2): the branch was not cut from the base — an orphan branch, or the
  wrong base. There is no change between the two for a review to read.
- **`review: <repo> is a shallow clone, and a merge base found in one can be
  the wrong one: …`** (exit 2): the repository was cloned at a depth — CI
  checks out one commit by default. Past the cut git may find no merge base,
  or an older one reachable through a merge, and a review would read the
  wrong change. Fetch the rest with `git fetch --unshallow`, or in GitHub
  Actions check out with `fetch-depth: 0`.
- **`review: git diff-tree failed: …`** (exit 2; `diff-tree` from phase 6), or another verb: git could not
  read the change, and its own reason follows. A partial clone
  (`--filter=blob:none`) is one way, its remote reachable or not: git lists
  the change, and the review never fetches the content the clone lacks
  (`lazy fetching disabled`), since nothing writes into the repository under
  review. Clone it without `--filter`.
- **`gate_lint — FAILED: ruff exited 2: …`** (phase 7, exit 3): the ruff on
  `PATH` could not run, and all it said follows. The secrets gate and the
  lanes still report; `uv run` puts the project's own ruff on `PATH`.
- **`review: no profile 'x'; there are default, gates-only`** (phase 7, exit 2):
  name one of those, or none for `default`, every check. A
  profile that names an unknown rule, and a rule file that will not load,
  are refused the same way, before anything runs.
- **`review: config.toml: [review] verify must be true or false`** (phase 7,
  exit 2): a setting in `phase_7_hardened/config.toml` missing, misspelt or
  of the wrong kind; the sentence names which.
- **`gate_rules — FAILED: rule …`** (phase 7, exit 3): a rule in
  `phase_7_hardened/rules/` raised, or a tree rule could not look: a file it
  asked for was not read whole, or the head's tree could not be listed; the
  other checks still report.
- **`review: no branch is checked out in …`** (phase 7, exit 2): a detached
  head, as CI checks out; name the branch to review with `--head`.
- **`review: nothing '…' changes lies under …`** (phase 7, exit 2): no file
  of the change is under that `--path`; git matches a path exactly, case
  included.
- **`review: REVIEW_PROVIDER=copilot needs a cached token`** (phases 6 and 7,
  exit 2): run
  the login once; if the token has expired, `uv run python
  scripts/copilot_login.py --force` renews it.
- **Every lane reports `FAILED: BadRequestError … model is not supported`**
  (exit 3): `REVIEW_MODEL` names a model the arm does not offer; leave it
  blank for the default. Phase 7 refuses a name no model class claims before
  anything is spent (`review: REVIEW_MODEL: …`, exit 2), on the Gemini arm.
- **`FAILED: RESOURCE_EXHAUSTED: 429: You exceeded your current quota …`** (exit 3,
  or findings "the verifier could not judge" under `--verify`): the Gemini
  free tier, measured at 5 requests a minute and 20 a day on
  `gemini-2.5-flash`. The lanes are 3 requests, and `--verify` adds one for
  each lane finding a gate has not already made: 10 in all on the planted
  branch before a lane's restatement of a gate went unasked, 5 and 7 in two
  Copilot runs since, 10 again in one Gemini run. Phases 4 and 5 pass the
  minute's five within one run, because their collector calls one tool a
  turn. The retries cover a blip of
  seconds, not a quota window: the lane or verifier is named and the run goes
  on. For the talk use a key with billing enabled, or the Copilot arm; on
  phase 7, `REVIEW_FALLBACK_MODEL=gemini-3.8-flash` puts a second model, and
  its own quota, behind the first. A `503 UNAVAILABLE … high demand` on one
  lane is the same story for one call.
- **Every verifier reports `ClientError: 404 NOT_FOUND … no longer available`:**
  `REVIEW_VERIFIER_MODEL` names a model the API does not serve to this key
  (`gemini-2.5-flash-lite` was one). The registry accepted the name, so the
  check up front passed; every finding is kept and named. Leave it blank.
- **`I could not reach the model: RESOURCE_EXHAUSTED: 429: You exceeded …`** as
  the agent's answer in `adk run` or `adk web`, from phase 4 on: the provider
  refused the call — a quota, an outage, a missing key — and the agent said
  so instead of ADK printing a traceback. The reviewers then answer "nothing
  was gathered" with the reason and the verdict never approves on it; the
  command names the failed agent and exits 3.
- **A traceback on phases 1 to 3, ending in a provider error:** those three
  are the smallest agents and have no error handling on purpose; the last
  line is the reason. In `adk web` the same error is a red box holding the
  provider's whole answer, and the traceback is in the terminal running the
  server.
- **A run uses a provider or model `.env` does not name:** a variable
  set in the shell wins over `.env` at every entry point — ADK 2.9.2
  restores what was set before it loads the file, and the commands load
  it without overriding — so a stale `export` decides. `unset` it, or run
  with `env -u REVIEW_PROVIDER`. The phase 6 and 7 reports name the model
  and arm that ran, and Vertex AI when `GOOGLE_GENAI_USE_VERTEXAI` sends
  the Gemini arm there.
- **`adk web` lists a phase but it will not load:** the folder was renamed
  to something that is not a Python identifier, or `.env` was moved from the
  root. Every phase finds the root `.env` by walking up from its own folder.
