# Phase 7 — hardened, and grouped by dependency direction

Phase 6, for those who want more. Two things happen at once. The code is
regrouped by what each part may depend on — `core/` is the domain and
imports nothing that runs a process or calls a model, `rules/` holds a
project's own checks, `config.toml` the profiles and the review policy, `collect/` gathers evidence, `judge/` is the model boundary, `deliver/` is the report, and
`review.py` is the driver — with a test that keeps every import pointing one
way. And what advanced users ask for after a live run is added on top: retries on both arms, a token ceiling that wraps up loudly, a
second deterministic gate, a second opinion on each lane finding a gate has not already made,
each changed file's blast radius, a project's own rules, grouped into
profiles, and a choice of what a review covers: one folder of a change, or
every file at the head. The chat shape, the verdict rule and the meaning of
each exit code are phase 6's; the command gains a flag for most additions,
and `--head` becomes optional.

## What changed since phase 6

Changed: `__init__.py`, `agent.py`, `review.py`. Moved: `config.py`, `lanes.py`,
`plugins.py`, `tools.py`. Every module now sits in the group it may depend
from:

| Group | May import | Holds |
|---|---|---|
| `core/` | nothing else | `blast.py` (new: what at the head depends on each changed file, read from the syntax tree), `findings.py` (`Finding`, `Review`, the severity scale), `rules.py` (new: the `Rule` and the `TreeRule` a project writes, the `Tree` a tree rule reads, what the rules find, the profile chosen), `secrets.py` (the credential shapes, `scrub`, the secrets gate), `text.py` (flat whitespace, the named cut), `verdict.py` (grounding, folding, deciding, `Outcome`) |
| `rules/` | `core` | new: a project's own rules, one self-contained class a file: `no_print.py` (the example of the shape), `money_in_cents.py` (the payments project's own), `reviewer_instructions.py`, `private_patch.py` and `tests_offline.py`, and the tree rules `required_paths.py`, `module_defines.py`, `derives_from.py` and `parameters.py`; `__init__.py` finds them |
| `collect/` | `core`, `rules` | `git.py` (read-only git, `collect_evidence`, every Python file at the head in one batch), `gates.py` (new: ruff at the head commit) |
| `judge/` | `core`, `rules`, `collect` | `config.py` (the request gains retries), `lanes.py` (and the read-back from state), `tools.py` (the model-facing tools and the guardrail), `plugins.py` (gains the ceiling), `graph.py` (the graph and the `App`; named so because `adk web` lists any folder holding an `agent.py` as an agent), `run.py` (new: one seeded run, guarded), `verify.py` (new: the second opinion) |
| `deliver/` | `core` alone: the driver hands it the rest | `report.py` (the report, and the rules that keep model prose from forging it) |
| the root | everything | `agent.py` builds the chat `App` for ADK's loader, the one place that wants it; `__init__.py` answers `agent` without loading it, so `core/` really does import alone; `review.py` is the driver that fixes the order of the steps; `config.toml` is the one config file |

`tests/test_layering.py` reads the imports off the syntax tree and fails,
naming every import that points the wrong way, and checks that `core/` and
`rules/` import nothing that calls a model or runs a process.

The additions:

- **Retries on both arms, from one request** (`judge/config.py`).
  `request_config()` carries `retry_options` beside the deadline it already
  carried: genai retries the request on the status codes it deems transient,
  with backoff, and ADK's LiteLLM wrapper forwards the same field as
  `num_retries`. Gemini asks for `RETRY_ATTEMPTS`; Copilot asks for one,
  because LiteLLM also retries around the OpenAI SDK, whose own two retries
  make its three. A role may pick its own model through `REVIEW_<ROLE>_MODEL`; the
  verifier does, and on the Gemini arm readiness resolves the model of every
  role the run builds. And
  `REVIEW_FALLBACK_MODEL` puts a second model behind every role's first,
  through ADK's `FallbackModel`: a 429 or a 5xx moves the call on, each model
  tried once, the request's retries spent first — on the free tier the quota
  is per model, so a second model is a second quota.
- **A token ceiling** (`judge/plugins.py`, `--max-tokens N`). Three lanes
  call at once, so the ledger reserves each call's cost before it is sent —
  its request over four, plus room for an answer — and refuses the call that
  would pass the ceiling, through the same plugin hook the redaction plugin
  uses. The refused lane is named, everything found is reported, exit 3.
- **A second gate: ruff** (`collect/gates.py`). The changed Python files are
  read from the head commit in one batch, as the blast radius reads the
  tree, written into a temporary directory, and ruff runs
  there, `--isolated` with the rules `config.toml`'s `[lint]` selects and ignores, never the reviewed repository's
  own configuration, and `--ignore-noqa`, so no comment in the branch
  silences it. Each file is written into a folder of its own, under a name
  of the gate's own (`module.py`, or `__init__.py` where the branch's is
  one), and named to ruff, so a `.venv/` the branch changed is linted,
  `x.py` beside `X.py/y.py` collides on no disk, and a `nul.py` or `a:b.py`,
  which Windows cannot hold, is linted like any other. Hits land under `gate_lint`; one on a line the secrets
  gate already reported folds into it. Without ruff on the path, or with one
  that fails, the gate did not look and says so: the run is degraded, exit 3,
  the reason in the report.
- **A second opinion** (`judge/verify.py`, `--verify`). One verifier per
  lane finding a gate has not already made, fanned out as a second graph the way the lanes are — the
  same `max_concurrency`, the same plugin instances, one seeded run — and
  before the fold, each answering a two-field schema: holds, and why. A
  refuted finding is dropped and named; one its verifier could not judge
  stays, named with the reason. The gates' findings are facts and are never
  asked about — nor lost: a gate's reading of a line stands whatever a
  verifier says of a lane's. Nor is a lane's finding that only says again
  what a gate found, no more severely: unasked, it goes to the fold as it
  would without `--verify`, which folds it into the gate's.
- **A blast radius** (`core/blast.py`). What at the head depends on each
  changed Python file, directly or through another file, with tests
  counted apart: read from git in one batch and parsed with Python's own
  `ast`, never run. The lanes read it in a section of their own beside the
  diff, told to weigh a change to shared behaviour by how far it reaches,
  as context and never as evidence: a finding that quotes it is dropped,
  like any quote that is not the change's own lines. Both shapes carry it: the
  command seeds it, and in chat the tool that lists the changed files
  writes it. Each line counts all that depends on the file and names the
  files that import it directly, the call sites a change meets. The report
  opens with it, widest first (the most modules importing a file directly,
  then the most reached), so a person knows where to read closely and where
  a skim will do. It never moves the
  verdict: severity decides. What was not read is never read as nothing: a
  file that is not Python is not measured, and when a file could not be
  parsed, was over its size cap or fell past the tree's byte budget, or the
  tree could not be listed at all, every count is a floor and says so; so is
  what a rule over the whole tree found, and only a rule that asks for an
  unread file by name is a hole.
- **Rules and profiles** (`core/rules.py`, `rules/`). A project's own
  check is one class in a file of its own in `rules/`: an id, a severity,
  a title, a fix, and `check(path, line)`, which reads each line the change
  added and answers yes or no. The rule decides its own scope, which files
  and which lines, so nothing about it is configured anywhere else; drop
  the file in and it is found. A tree rule, `check(tree)`, reads the head
  instead of the added lines: every path, and each Python module parsed once
  with the blast radius, for what must exist, define a name, derive from a parent or take a
  parameter; its expectations are its own constants. A rule is for what no tool checks: ruff covers
  the rest, with the families `[lint]` selects. `config.toml`, the phase's one config file
  beside `review.py`, names profiles under `[profiles]`, each a
  list of the checks it runs — the built-in ones, `secrets`, `lint`,
  `lane.security`, `lane.tests` and `lane.complexity`, and the folder's own
  by id — and `--profile NAME` picks one. With none named, a review runs
  `default`: every built-in check and every rule in the folder, so a new
  rule runs until a profile leaves it off, and no `[profiles]` at all is
  no error. The same file holds the review policy, `[review]`'s `fail_on`,
  `max_tokens` and `verify`, each a flag's default that the flag overrides for one run, and `[lint]`'s ruff rules and the ones it ignores, which only the file sets; it is read whole, and a
  setting missing, misspelt or of the wrong kind is a sentence and exit 2. On the planted branch the payments project's own rule,
  `money-in-cents`, finds `report.py`'s `amount_cents / 100`, which neither
  ruff nor the secrets gate can see; `charge.py` divides the same way, but
  on `main` already, and a rule reads only what the change added.
  Everything is read from this folder and nothing from the
  repository under review. A profile without a lane calls no model and
  needs no key, so `gates-only` can run on every push. The report's header
  names the profile and what it left off, and a lane left off was never
  asked, so it never reads as a failed one. Redaction is not a check: every
  model call is redacted whatever the profile. The file is checked whole:
  a profile that is no list, turns nothing on or names a rule no one
  wrote, a rule file that will not load and an id two rules share are each
  a sentence and exit 2 before anything runs; a rule that raises, or exits,
  or a tree rule that could not look, a file it asked for not read whole or
  the head's tree not listed, is named under `gate_rules` and the run is
  degraded, exit 3. With no lane
  on, a file cut at the diff cap is no hole: the cap is the lanes' limit,
  and the gates and the rules read every added line.
- **What a review covers** (`review.py`, `collect/git.py`). `--path DIR`,
  repeatable, keeps a review to what lies under those folders; the report
  names the scope and how many changed files it left out, which a person
  chose, so they are no hole. `--all` reviews every file at the head, not
  what it changes: the head is diffed against git's empty tree, which git
  knows without storing, so every file reads as added and goes through the
  same gates, lanes and grounding, and no merge base is needed, so a shallow
  clone serves. `--head` is the branch checked out when not given. With
  neither `--base` nor `--all`, a person at a terminal is asked which, on
  stderr, and only when stdin and stderr are both the terminal, so a
  `2>/dev/null` never waits on a question no one sees; CI or
  a script, which nothing can ask, reviews the change against `main`, or
  `master` where there is no `main`, as the command always did. Nothing
  reads the repository's `.gitignore`: git keeps an ignored file out of
  every commit, so it never reaches a review, and what a filter by it would
  skip is only what was committed anyway, a force-added `.env` whose key
  was then approved. What the lanes read is capped in all, as each diff
  is: past 250,000 characters a file is left out whole, the block's end
  tells the lanes how many, and the report names each under "not read";
  the blast radius beside it is cut at 20,000, widest first. With no cap,
  `--all` over 4,826 files gave each lane and each verifier 14.9 MB.

## Run it

```bash
uv run python scripts/make_demo_repo.py                                        # once
uv run python -m phase_7_hardened.review --head feature/payments               # phase 6's report, plus the profile, the blast radius, gate_rules and gate_lint
uv run python -m phase_7_hardened.review --head feature/payments --verify      # a second model judges each lane finding
uv run python -m phase_7_hardened.review --head feature/payments --max-tokens 2000   # the ceiling refuses what would pass it
uv run python -m phase_7_hardened.review --head feature/payments --profile gates-only  # gates and rules only: no model, no key
uv run python -m phase_7_hardened.review --head feature/payments --path src/payments/config.py   # one folder or file of the change
uv run python -m phase_7_hardened.review --all --profile gates-only                # every file at the branch checked out, not a change
uv run pytest -q tests/test_hardened.py tests/test_layering.py                 # the additions and the layering, offline
```

At a terminal, a command with neither `--base` nor `--all` first asks what to
review; `--base main` skips the question.

Chat still works: `uv run adk web .` and pick `phase_7_hardened`. To see the
regrouping as a diff, compare `phase_6_reviewer/` with `phase_7_hardened/judge/`,
where most of it went.

## What to notice

- The grouping is the architecture. Nothing in the behaviour changed when the
  files moved; what changed is what each file is allowed to know, and a test
  now says so. `core/` can be read, and tested, without ADK installed — and a
  test does that too, because the syntax tree cannot see what an import
  loads: with the scaffold's eager `from . import agent` in the package root,
  importing `core/` measured 187 ADK modules loaded.
- Retries live in the clients, not in the graph, and are set once on the
  request, which both arms read — the way the deadline already was. ADK's
  node `retry_config` re-runs a whole lane, and with the model-error plugin
  turning errors into answers it would never see one; the clients retry the
  transient status codes they know, with backoff, and the plugin still
  catches what outlasts them. Seen live on Gemini's free tier: five requests
  a minute per model, and `--verify` on the planted branch made ten, so the
  last verifiers met a 429 asking for 39 seconds — past three attempts a few
  seconds apart — and their findings were kept and named with it.
- A ceiling that only counted tokens already spent would let three concurrent
  lanes through and be passed by all three. Reserving first is what makes it
  a ceiling; one hook releases, because ADK hands the after-hook the error
  plugin's answer as well, and a call that failed is attempted, never
  completed.
- Two gates and three lanes can all find one line; the report carries it
  once: the most severe reading first, whole, the first source on a tie —
  secrets, the folder's rules, ruff, then the lanes, which is the report's
  order too — and any finding one kept already holds — its lines, or,
  unplaced, its quote — folds into it. Measured on
  the planted branch: four folds offline, five and six live. Compared only
  with the first finding it overlapped, a lane's blocker quoting a whole
  function had replaced ruff's line 27 and left S602 on line 28 beside it.
  A folded finding is still named, under its own source: "folded into
  `lane_security`'s finding on the same lines: S602 …". Rehearsed live
  before, every ruff hit folded into the lane's blocker and ruff's section
  read "no findings" under the gate the step is about.
- The verifier is the one place a model can remove a finding, so it never
  does so silently: the reason is in the report, and a verifier that fails
  leaves the finding in place, with why. It runs before the fold, so what a
  gate found stands whatever it says — and it is the first graph's shape
  again, one agent per finding, so the ledger prices each.
- An import graph is a floor of what a change reaches. A module loaded by
  name, a subprocess, a web route or a plugin registry is invisible to it,
  which is why the radius tells a reader where to look and never decides.
  On the planted branch it puts `charge.py` first: `refund.py` and the
  tests depend on it, while the three new files are leaves.
- A rule is code and a profile is a list, and neither lives in the
  repository under review. A branch that could choose its own profile could
  switch its own secrets gate off, and the reviewer would depend on what it
  reviews. A rule held in a config file — a pattern and a list of paths — is
  a second language to learn; a class that answers yes or no is the Python
  a reader already knows, and the one choice left to the command line is
  which list to run.

## Left out on purpose

Baselines and dismissals, SARIF output, a scorecard that checks the gates
still find planted defects, and lanes made to cite a rule. Each is a product
feature, not an ADK lesson, and each is more of the same shape: a
deterministic step, counted, named in the report. A rule registry was on
this list until a project asked for rules of its own; what came in is the
smallest shape that holds them.
