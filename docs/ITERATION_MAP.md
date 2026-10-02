# ADK by iteration — from hello world to a branch reviewer

A seven-phase demo introducing Google ADK. Each phase folder is a standalone
agent that copies the previous one and adds one layer, so the audience
watches the reviewer grow. Section 2 is the slide, sections 4–10 the script
for each step, section 11 how the folders get built.

---

## 1. What is being taught, and in what order

| Phase | Folder | One sentence | New ADK concepts |
|---|---|---|---|
| 1 | `phase_1_hello_world` | The smallest legal agent, on either provider | `Agent`, `root_agent`, `adk run`, `adk web`, `.env` discovery, `LiteLlm` |
| 2 | `phase_2_preflight` | The agent proves a repo and two branches exist | function tools, docstring-as-schema, the `{status: …}` envelope |
| 3 | `phase_3_changed_files` | The agent lists what changed and shows a capped diff | `before_tool_callback` guardrails, `ToolContext.state`, capped output |
| 4 | `phase_4_first_review` | One reviewer returns typed findings, in chat or as a command | `Workflow`, `output_key` → `{placeholder}`, `output_schema`, `on_model_error_callback`, `InMemoryRunner` |
| 5 | `phase_5_parallel_lanes` | Three reviewers judge in parallel | fan-out + `JoinNode`, `max_concurrency`, per-agent models, thinking budgets |
| 6 | `phase_6_reviewer` | Evidence first, lanes judge, code decides | `App` + plugins, the model-error hook as a plugin, one request deadline, verdict and exit code in code |
| 7 | `phase_7_hardened` | Optional: phase 6 regrouped by dependency direction, hardened | layering test, retries and `FallbackModel`, a token ceiling, a verifier per finding, a blast radius, rules by profile |

The talk gives each live phase five to ten minutes, 40 in all for the six,
and phase 7 three as a pointer. Phases 4–7 make real
review calls, so the talk needs Copilot or a billed Gemini key: the free
tier's 5 requests a minute and 20 a day cannot carry it. When a quota
bites, the failed lane or verifier is named and the rest is reported.

**Both providers, every phase, Copilot first.** The talk is given on
Copilot, so it is the default arm and the one measured first; every folder
works on Gemini too. One `.env` variable chooses, and only `config.py`
names a provider.

---

## 2. The slide: the iteration map

```
phase 1  hello        Agent + config(copilot | gemini) ───────  adk web / adk run, either arm
phase 2  preflight    Agent + tools(git) ─────────────────────  "does this repo and branch exist?"
phase 3  changed      Agent + tools + guardrail + state ──────  "what did the branch change?"
phase 4  first review Workflow: collector → reviewer(schema) ─  "is this change OK?"  (typed findings)
                      + review.py: the same graph from the shell, arguments in, an exit code out
phase 5  lanes        Workflow: START → (security, tests, complexity) → join → verdict
phase 6  reviewer     review.py: git evidence in Python → Runner → lanes → verdict → exit code
                      App + plugins: redaction, spend ledger, provider errors as a lane's own answer
phase 7  hardened     core/ rules/ collect/ judge/ deliver/ ─  the same reviewer, grouped by what it may depend on
                      + retries, a token ceiling, a ruff gate, a second opinion, a blast radius, a project's rules
                      (optional, for advanced users)
```

Each arrow down the page is "copy the folder, add one thing".

---

## 3. Shape of the repository

```
adk_review_demo/
├── .env                      # ONE file, shared by every phase (gitignored)
├── .env.example
├── .gitattributes            # LF in every checkout, whatever core.autocrlf says on the machine; the slide exports are binary
├── .github/
│   ├── copilot-instructions.md   # Copilot's guide to this repository: the short form of CLAUDE.md
│   ├── pull_request_template.md  # the checklist the tests and CI enforce, for a person or an agent opening a pull request
│   ├── agents/
│   │   └── phase-author.agent.md # a custom Copilot agent that changes a phase the way the tests demand and carries it forward
│   ├── instructions/             # path-specific Copilot instructions, each applied to the files its applyTo names
│   │   ├── docs.instructions.md
│   │   ├── phase-7.instructions.md
│   │   ├── phases.instructions.md
│   │   └── tests.instructions.md
│   ├── skills/                   # agent skills for the recurring tasks
│   │   ├── carry-forward/
│   │   │   └── SKILL.md
│   │   ├── docs-tree/
│   │   │   └── SKILL.md
│   │   ├── new-rule/
│   │   │   └── SKILL.md
│   │   └── review-a-branch/
│   │       └── SKILL.md
│   └── workflows/
│       ├── ci.yml                # lint and the offline suite on Windows, Linux and macOS, on every push
│       └── copilot-setup-steps.yml # the cloud agent's environment before it starts: uv sync --locked
├── azure-pipelines.yml       # the same checks on Azure DevOps, where the repository is also kept
├── .python-version           # 3.13: every measurement here ran on it, and `>=3.13` alone let uv pick a newer one
├── pyproject.toml            # google-adk[extensions]==2.9.2 (extensions brings litellm, the Copilot arm), python-dotenv
├── Makefile                  # optional: the same uv commands as targets, for those who like make
├── README.md                 # how to run the demo in five minutes
├── CLAUDE.md                 # guidance for Claude Code: commands, the phase rules, what the tests pin
├── docs/
│   ├── ITERATION_MAP.md      # this file
│   └── presentation/         # the talk's slides, exported from the deck; "basic fonts" = Arial and Courier New, for a machine without the deck's
│       ├── ADK_Code_Reviewer_KT.pdf
│       ├── ADK_Code_Reviewer_KT.pptx                        # without the speaker notes
│       ├── ADK_Code_Reviewer_KT_with_notes.pptx             # with them
│       ├── ADK_Code_Reviewer_KT_basic_fonts.pptx            # without the notes, basic fonts
│       └── ADK_Code_Reviewer_KT_basic_fonts_with_notes.pptx # with the notes, basic fonts
├── scripts/
│   ├── make_demo_repo.py     # builds the throwaway repository the demo reviews; --fix commits the two fixes
│   ├── ask.py                # one headless turn through any phase: uv run python scripts/ask.py <phase> '...'
│   ├── rehearse.py           # every phase's demo line in order, paced: the evening before the talk
│   ├── measure.py            # how often the lanes find what the demo plants, over N live runs
│   └── copilot_login.py      # GitHub's device flow with its full window; caches the Copilot token
├── tests/                    # offline, no key: a fake model in ADK's registry, every phase through the real engine
│   ├── conftest.py           # FakeModel (fake.*, can be told to raise), demo_repo, load_phase, run_turn
│   ├── test_wiring.py        # the loader lists every phase, both arms build, the guardrail is attached, one fake turn
│   ├── test_git_tools.py     # the read-only git tools against a real repository; the cached preflight
│   ├── test_callbacks.py     # the path guardrail
│   ├── test_review_graph.py  # phase 4 and 5 graphs through the real Workflow
│   ├── test_reviewer.py      # phases 6 and 7: evidence, gate, grounding, dedupe, plugins, a failed lane, the report, exits 0/1/2/3
│   ├── test_copilot.py       # the files under .github hold to their formats: applyTo, front matter, one pinned commit per action
│   ├── test_docs.py          # the map's tree, each README's file claims and the paths the guides name, read the way a reader does
│   ├── test_failures.py      # a provider error is a sentence where the hook runs, a traceback where it does not; ask.py's two promises
│   ├── test_hardened.py      # phase 7: retries on both arms, the ceiling, the ruff gate, the second opinion, the blast radius, rules and profiles
│   ├── test_layering.py      # phase 7: every import points one way, and core and rules run nothing
│   └── test_portability.py   # what has to hold on Windows, read off the source
├── phase_1_hello_world/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py
│   ├── agent.py
│   └── config.py             # build_model(): gemini string or LiteLlm("github_copilot/…")
├── phase_2_preflight/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py
│   └── tools.py
├── phase_3_changed_files/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py
│   ├── tools.py
│   └── callbacks.py
├── phase_4_first_review/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py           # imports nothing: the command reads .env before any agent is built
│   ├── agent.py
│   ├── config.py
│   ├── tools.py
│   ├── callbacks.py
│   ├── schemas.py
│   └── review.py             # the same graph as a command: python -m phase_4_first_review.review --head <branch>
├── phase_5_parallel_lanes/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py             # gains lane_planner()
│   ├── tools.py
│   ├── callbacks.py
│   ├── schemas.py
│   └── review.py             # the verdict's first line as the exit code
├── phase_6_reviewer/
│   ├── README.md             # what it does, what changed since the previous phase, how to run it
│   ├── __init__.py
│   ├── agent.py              # root_agent + app, so `adk web` still works
│   ├── tools.py
│   ├── config.py
│   ├── lanes.py              # lane table, lane factory, the finding schema
│   ├── plugins.py            # the three plugins (redaction, the ledger, provider errors) and the secrets gate
│   └── review.py             # the CLI: python -m phase_6_reviewer.review [repo] --head <branch> [--base main]
└── phase_7_hardened/         # optional: phase 6 regrouped by dependency direction, plus what advanced users ask for
    ├── README.md             # what it does, what changed since the previous phase, how to run it
    ├── __init__.py           # answers `agent` without loading it, so core/ imports alone
    ├── agent.py              # the loader's entry: builds the chat App, the one place that wants it
    ├── config.toml           # the one config: the review policy, ruff's rules and ignores, the profiles
    ├── review.py             # the driver: config → profile → what to review → gates and rules → lanes → (verify) → fold → verdict
    ├── core/                 # the domain, pure: imports no other group, no ADK, no process
    │   ├── __init__.py
    │   ├── blast.py          # what depends on each changed file at the head, read from the syntax tree
    │   ├── findings.py       # Finding, Review, the severity scale
    │   ├── rules.py          # the Rule and the TreeRule a project writes, what they find, the profile chosen
    │   ├── secrets.py        # the credential shapes, scrub, the secrets gate
    │   ├── text.py           # the two string rules every group shares: flat whitespace, a cut that names itself
    │   └── verdict.py        # grounding, folding, deciding; Outcome
    ├── rules/                # a project's own rules, one a file; may import core
    │   ├── __init__.py       # finds the rules, line rules and tree rules alike
    │   ├── derives_from.py   # a tree rule: a class named like this derives from that
    │   ├── module_defines.py # a tree rule: a module defines these names
    │   ├── money_in_cents.py # the payments project's rule: money stays in whole cents
    │   ├── no_print.py       # a generic rule: print() left in library code
    │   ├── parameters.py     # a tree rule: a function takes these parameters
    │   ├── private_patch.py  # a test that patches a private name
    │   ├── required_paths.py # a tree rule: these files and folders exist
    │   ├── reviewer_instructions.py # text that tries to instruct the reviewing model
    │   └── tests_offline.py  # a test that reaches the network
    ├── collect/              # driven adapters gathering evidence; may import core and rules
    │   ├── __init__.py
    │   ├── git.py            # read-only git, collect_evidence
    │   └── gates.py          # the second gate: ruff at the head commit
    ├── judge/                # the model boundary; may import core, rules and collect
    │   ├── __init__.py
    │   ├── config.py         # provider; the request: temperature, deadline, retries on both arms; readiness
    │   ├── lanes.py          # the lane table and factory, the blast radius section they read, the read-back
    │   ├── tools.py          # the model-facing tools and the guardrail
    │   ├── plugins.py        # redaction, the ledger and its ceiling, provider errors
    │   ├── graph.py          # the graph and the App, as factories; nothing built at import
    │   ├── run.py            # one seeded run through the engine, guarded: the driver's lanes and the verifier share it
    │   └── verify.py         # the second opinion: one verifier per finding, a second graph
    └── deliver/              # what a person sees; may import core alone, handed the rest by the driver
        ├── __init__.py
        └── report.py         # the report, and the rules that keep prose from forging it
```

**Why the phase folder is the agent folder.** ADK's loader treats
`<agents_dir>/<name>/agent.py` as an agent named `<name>`, so
`uv run adk web .` lists every phase in one dropdown. Each `root_agent.name`
equals its folder name.

**Why one `.env` works.** ADK's `load_dotenv_for_agent` loads the first
`.env` found walking up from the agent folder, so one file at the root
serves every phase; the commands from phase 4 on, and `scripts/ask.py`, load
it themselves. Nothing else is
shared: each phase carries its own copy of every module it uses.

**The central `.env`, abridged (`.env.example` is whole):**

```
REVIEW_PROVIDER=copilot       # copilot | gemini; copilot when blank
REVIEW_MODEL=                 # blank = gpt-4.1 / gemini-2.5-flash
# copilot needs no key: run `uv run python scripts/copilot_login.py` once
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=...            # the gemini arm
```

**ADK 2.9.2 practice, in its simplest form.** Six habits, each introduced
once: the folder layout `adk create` scaffolds; one function choosing the
model, so both arms are the same `LlmAgent`; tools that return a
`{status: …}` dict and never raise; state passed with `output_key` and
`{placeholder}`; `Workflow` for known shapes, `JoinNode` for fan-in; and
`App` carrying plugins, exported as `app` because the loader looks for it
first. Context caching, evaluation sets, MCP and A2A get a sentence on the
last slide, not a phase.

**macOS and Windows, both.** The team runs both, so no phase assumes a
POSIX shell or path: git's output, for example, is decoded as UTF-8 by
hand, because a Windows console is a code page. `tests/test_portability.py`
reads these rules off the source.

**The repository under review.** A live audience should not wait for a
real branch, so `scripts/make_demo_repo.py` builds `<demo repo>`
(`adk-demo-repo` in the platform's temp directory): a clean `main` and a
`feature/payments` branch changing four files, each with one obvious
defect — `subprocess.run(..., shell=True)`, a hard-coded AWS key pair, a
function with no test, a copy-pasted block. Phases 2–7 run against it.

---

## 4. Phase 1 — hello world

**Goal.** The whole ADK loop in the least code: one agent, two providers,
two ways to run it.

**Files.** `__init__.py`, `config.py`, `agent.py`, whose one `Agent` has
no tools. `config.py` is the only place a provider is named:

```python
if provider == "gemini":
    return model
return LiteLlm(model=f"github_copilot/{model}")
```

**Demo.** `adk run` or `adk web .`, then again with `REVIEW_PROVIDER=gemini`:
the event cards, the talk's debugger, show only the model name change.

**Say.** `Agent` is `LlmAgent`; the loader looks for `root_agent`; Gemini
is a string because it is native, the rest go through `LiteLlm`.

**Exit criteria.** `adk web .` lists the agent; both arms answer a greeting.

---

## 5. Phase 2 — preflight

**Goal.** Prove a repository and two branches exist, and print a preflight
block before anything else.

**New file.** `tools.py`: `_git` runs read-only git as an argv list with a
timeout, never through a shell, and `inspect_repository(repo, base, head)`
refuses a shallow clone or a name that means two refs rather than guess.

**Changed file.** `agent.py` gains the tool and stores a five-line block
(repository, branch @ sha, against @ sha, merge-base, commits ahead) under
`output_key="preflight"`.

**Demo.** Review `feature/payments` against `main`, then a branch that does
not exist: a sentence comes back, not a stack trace.

**Say.** The docstring is prompt material: ADK builds the tool schema from
it. A tool answers `{status: success|error}` and never raises at the model.

**Exit criteria.** Correct SHAs; a wrong branch gives one polite sentence.

---

## 6. Phase 3 — changed files

**Goal.** List the branch's changed files and show any one diff; the first
phase that treats a tool argument as hostile input.

**New in `tools.py`.** `inspect_repository` leaves its scope in
`tool_context.state`, so the new tools take no repository. `changed_files`
stores the allowlist there; `show_diff` cuts a diff at 4,000 characters
with a visible marker, since the model reports a cut it cannot see as a bug.

**New file.** `callbacks.py`: `only_changed_paths` refuses a path not in
the allowlist, a `repo` that is not a directory and a `path` with `..`; as
a `before_tool_callback`, its dict answers without running the tool.

**Changed file.** `agent.py` adds the two tools and the callback.

**Demo.** Ask for the diff of `src/payments/charge.py`, then of
`/etc/passwd`: the refusal is the point.

**Say.** Tool arguments come from the model, so they are untrusted input;
`ToolContext.state` turns one tool's answer into another's allowlist.

**Exit criteria.** Four changed files listed; the invented path refused
before the tool runs.

---

## 7. Phase 4 — the first review

**Goal.** One reviewer returns findings code can read, not prose.

**New file.** `schemas.py`, a `Review` of findings and a `summary`;
`evidence` is required, so every finding quotes the lines it rests on:

```python
class Finding(BaseModel):
    file: str
    line: int | None = None
    severity: Literal["blocker", "major", "minor"]
    title: str
    evidence: str
    suggestion: str
```

**Changed file.** `agent.py` becomes a collector that gathers the diffs
without judging and a reviewer that answers in the schema:

```python
root_agent = Workflow(name="phase_4_first_review", edges=[("START", collector, reviewer)])
```

**Changed file.** `config.py` gains `request_config()`, temperature zero so
a severity is a decision, not a sample, and `when_the_model_fails`, an
`on_model_error_callback` whose response takes the error's place: a quota
or an outage is the agent's answer, not sixty lines of traceback, and a
schema agent's answer stays in its schema, or validation fails. Phases 1 to
3 keep the traceback: a graph is where the answer's shape starts to matter.

**Changed file.** `callbacks.py` gains `without_evidence`, a
`before_agent_callback` that skips the reviewer when the collector failed
or left no diff, and returns a `Review` with no findings that says why: "did not look" must
never read as "found nothing".

**New file.** `review.py`, the same graph as a command (section 12 has why):

```bash
uv run python -m phase_4_first_review.review <demo repo> --base main --head feature/payments
```

It prints the review as JSON. Exit 0: judged; 2: an unknown provider, path
or branch, before any model call; 3: an unreachable provider, no review, or
any other error, never Python's own exit 1.

**Changed file.** `__init__.py` drops `from . import agent`: `python -m`
imports the package, and so `agent.py`'s agents, before `.env` is read.

**Demo.** Point at the planted `shell=True` in the JSON in state, then run
the command: JSON on stdout, exit 0.

**Say.** ADK 2.9.2 allows `tools=` and `output_schema=` on one agent, but
gathering and judging are different jobs. `output_key` writes state and
`{diff}` reads it back; a one-edge `Workflow` is a sequence, and the same
class fans out next phase.

**Exit criteria.** `state["review"]` has the `shell=True` finding, `major` or
`blocker`, quoting the line; the command exits 0, and 2 on a missing branch.

---

## 8. Phase 5 — parallel lanes

**Goal.** Three specialised reviewers judge the same diff at once, the join
waits for all of them, and the provider chosen in phase 1 is still the only
provider-specific line of code.

**Changed file.** `config.py` gains one function:

```python
def lane_planner(thinking_budget: int) -> BasePlanner | None:
    """A thinking budget where the provider has one; nothing where it does not."""
```

**Changed file.** `agent.py` gains a lane factory and the fan-out:

```python
lanes = tuple(build_lane(*lane) for lane in LANES)  # security, tests, complexity
root_agent = Workflow(
    name="phase_5_parallel_lanes", edges=[("START", collector, lanes, join, verdict)], max_concurrency=3
)
```

`schemas.py` is unchanged: ADK's LiteLLM wrapper maps `output_schema` to a
JSON-schema response format, so every lane returns a `Review` on both arms.

**Changed file.** `review.py` exits 0 on APPROVED and 1 on REQUEST CHANGES,
read from the verdict's first line: the model's word, which phase 6
replaces with code. A failed agent, or neither word, is exit 3.

**Demo.** Same message as phase 4: three lane calls overlap in the Events
panel, the join fires once, the verdict cites all three. On Gemini the
usage line adds thinking tokens. The command exits 1 on the planted branch.

**Say.**

- Fan-out is an inner tuple in the edge; `JoinNode` waits for every branch;
  `max_concurrency` is the knob a free-tier key needs.
- The model is chosen per agent, so cheap models can do mechanical stages.
- `BuiltInPlanner` sets a thinking budget only Gemini honours;
  `PlanReActPlanner` fails beside `output_schema`, so off Gemini, no planner.
- Measured on Copilot: with no redaction plugin yet, this phase printed the
  planted AWS key back in its verdict. Phase 6 stops that.

**Exit criteria.** Three lane outputs in state; the verdict names all
three; switching the provider in `.env` changes only the model name; the
command exits 1 on the planted branch.

---

## 9. Phase 6 — the reviewer

**Goal.** Phase 5's command, rebuilt so a team can trust its exit code:
evidence in Python first, lanes only judge, code decides the verdict.

**Files (seven).**

| File | Holds |
|---|---|
| `tools.py` | git, the path guardrail, `collect_evidence` |
| `config.py` | `build_model`, `require_ready`, `request_config` (temperature zero, one deadline) |
| `lanes.py` | the lane table, `Finding`, `Review`, `lane_review` |
| `plugins.py` | `RedactSecretsPlugin`, `UsageLedger`, `ReportProviderErrors`, `scan_secrets` (the secrets gate) |
| `agent.py` | `build_app(chat=)`, `app`, `root_agent` |
| `review.py` | the CLI |
| `__init__.py` | |

**The CLI.**

```bash
uv run python -m phase_6_reviewer.review <demo repo> --base main --head feature/payments
```

1. Loads `.env` and checks the arm: a typo is exit 2 before any spend.
2. Runs `collect_evidence`; the secrets gate reads every whole diff here.
3. Runs `build_app(chat=False)` with the three plugins over seeded state.
   No intake agent: its `output_key` would overwrite the seeded evidence.
4. Drops findings whose quote is not whole lines of their own file's diff,
   folds overlaps, and decides in code: at or above `--fail-on`,
   `REQUEST_CHANGES`, exit 1; a failed lane, a file no lane read whole, or
   an unsupported quote at the bar, `DEGRADED`, exit 3; else `APPROVED`,
   exit 0. The bar is `blocker`: a lane's severity varies between runs.
5. Prints a markdown report with the counters and the ledger's spend line.

**`agent.py` still serves `adk web`.** `build_app(chat=True)` adds an
intake agent that fills the same state from chat. Both `app` and
`root_agent` are exported: a bare `root_agent` would lose the plugins.

**Demo.**

```bash
uv run python -m phase_6_reviewer.review --head feature/payments
echo $?   # 1: the key pair is two gate blockers, the shell=True a lane blocker
```

After `make_demo_repo.py --fix` the review is APPROVED, exit 0. Measured on
Copilot, one run in two rated a fix that still called `lp` a major, so the
fix spawns nothing: the severity is the model's, the bar the operator's.

**Say.**

- The order is the architecture: evidence, judgement, decision.
- A plugin is registered once on the `App` and no agent can opt out, so
  redaction belongs there; callbacks are per agent.
- Grounding compares the diff lines as the lane saw them, `+` markers
  stripped and secrets scrubbed: measured, real findings were dropped for
  quoting without the markers or quoting the redaction placeholders.
- With the plugin on, no lane saw the AWS key, so secrets are found by
  code, in the gate. Gates find; lanes only judge.
- The ledger exists because an expensive run should not look like a cheap one.

**Exit criteria.** Exit 1 on the planted branch (the key by the gate, the
shell by a lane); exit 0 after the fix; three ledger rows; `adk web .`
still runs phase 6.

---

## 10. Phase 7 — hardened, and grouped by dependency direction (optional)

**Goal.** For "and how would this grow?": phase 6 regrouped by what each
part may depend on, a test keeping the direction, plus what people ask for
after a live run. Phase 6's order and verdict rule stay.

**The regrouping.** Six groups, every import pointing one way, checked by
`tests/test_layering.py`:

| Group | May import | Holds |
|---|---|---|
| `core/` | nothing — no ADK, no process | `blast.py`, `findings.py`, `rules.py`, `secrets.py`, `text.py`, `verdict.py` |
| `rules/` | `core` | a project's own rules, one class a file |
| `collect/` | `core`, `rules` | `git.py`, `gates.py` (ruff) |
| `judge/` | `core`, `rules`, `collect` | config, lanes, tools, plugins, `graph.py`, `run.py`, `verify.py` |
| `deliver/` | `core` alone | `report.py` |
| the root | everything | `agent.py`, `review.py`, `config.toml` |

A test also imports `core/` with `google` unimportable: the syntax tree
cannot see what an import loads, and with an eager `from . import agent`
in the package root, importing `core/` loaded 187 ADK modules.

**The additions.**

1. **Retries on both arms, from one request** (`judge/config.py`). One
   `retry_options`: genai retries with backoff; LiteLLM reads it as
   `num_retries` and the OpenAI SDK under it retries too, so Copilot asks
   for one to get three. `RUN_DEADLINE_S` bounds the run. A blip is not a
   quota window: `REVIEW_FALLBACK_MODEL` adds a second model, and
   `REVIEW_<ROLE>_MODEL` gives a role its own.
2. **A token ceiling** (`judge/plugins.py`, `--max-tokens N`). Three lanes
   call at once, so the ledger reserves each call's cost before sending it
   and refuses the one that would pass the ceiling; exit 3, all reported.
3. **A second gate: ruff** (`collect/gates.py`). Ruff runs `--isolated
   --ignore-noqa` on the changed files from the head commit: a change must
   not configure or silence the gate that judges it. Overlaps fold into the
   most severe reading, since keeping the first title made "line too long"
   a blocker. No ruff, or a failing one, is degraded, exit 3.
4. **A second opinion** (`judge/verify.py`, `--verify`). One verifier per
   lane finding a gate has not already made, never per gate finding, which
   is a fact. A refuted finding
   is dropped and named; one that could not be judged stays, with why.
5. **A blast radius** (`core/blast.py`, read by `collect/git.py`). What at
   the head depends on each changed Python file, from `ast`: context for
   the lanes, the report's opening, never read by the verdict. The tree's
   budgets are `collect/git.py`'s, the radius's cut `judge/lanes.py`'s, and
   what was measured is in section 12.
6. **Rules and profiles** (`core/rules.py`, `rules/`). A rule is one class
   a file with `check(path, line)` over each added line; a profile in
   `config.toml` is a named list of rule ids and built-in checks, `default`
   running all. Nothing is read from the repository under review. The file
   also holds the review policy and is read whole: a bad setting is exit 2.
   A tree rule, `check(tree)`, reads the head instead: every path, and each
   Python module, parsed once with the blast radius, for what must exist,
   define a name, derive from a parent or take a parameter; its expectations
   are its own constants.
7. **What a review covers** (`review.py`, `collect/git.py`). `--path DIR`
   keeps a review to one folder; `--all` diffs every file against git's
   empty tree. With neither `--base` nor `--all`, a terminal asks and a
   pipeline uses `main`, or `master`. The lanes' diffs are capped at
   250,000 characters; a file past the cap is named under "not read".

**Demo.**

```bash
uv run python -m phase_7_hardened.review --head feature/payments --verify
uv run python -m phase_7_hardened.review --head feature/payments --profile gates-only  # no model
```

At a terminal, a command with neither `--base` nor `--all` first asks what
to review; `--base main` skips the question, as `scripts/rehearse.py` passes it.

**Say.** The grouping is the architecture, and a test keeps it. Retries
live in the clients: ADK's node retry re-runs a whole lane and, with errors
turned into answers, would never fire. A ceiling that does not reserve is
not a ceiling. The verifier never removes a finding silently. An import
graph is a floor of what a change reaches, so the radius never decides. A
branch that could choose its own profile could switch off its secrets gate.

**Left out on purpose.** Baselines and dismissals, SARIF, the scorecard,
lanes made to cite a rule: product features, not ADK lessons. The rule
registry was on this list until a project asked for rules of its own;
section 12 says what came in.

**Exit criteria.** `tests/test_layering.py` passes, fails on a planted
upward import, and imports `core/` with ADK absent; `gate_lint` carries
`S602` and `E501`, `S105` folded; `--max-tokens 100` exits 3; `--verify`
can refute every lane finding no gate made; the report opens with the blast radius;
`--profile gates-only` calls no model and finds `money-in-cents` at
`report.py:5`; an unknown profile is exit 2; `adk web .` runs phase 7.

---

## 11. Implementation plan

All eight steps, 0 to 7, are done and their acceptance lines met; what
changed after the build is in section 12. Each phase is copied from the one
before it and then extended, so a diff between two phase folders is exactly
the phase's lesson.

**Step 0 — the root.** `pyproject.toml` (Python 3.13,
`google-adk[extensions]==2.9.2`, `python-dotenv`), `.env.example`,
`.gitignore`, an optional `Makefile`, `README.md`, and
`scripts/make_demo_repo.py`, which builds the repository under review
idempotently. Each later step adds one folder.

**Step 1 — phase 1.** Three files. Acceptance: a greeting returns on both
arms, after the one-time Copilot login (`scripts/copilot_login.py`).

**Step 2 — phase 2.** Add `tools.py`. Acceptance: the preflight block for
the demo repo; a missing branch yields a sentence.

**Step 3 — phase 3.** Add `changed_files`, `show_diff`, `callbacks.py`.
Acceptance: the invented path is refused before any tool runs; a diff is
cut at the cap with the marker visible.

**Step 4 — phase 4.** Add `schemas.py`, split collector and reviewer, add
the `Workflow`. Acceptance: the `shell=True` finding with quoted evidence
in state, on both arms.

**Step 5 — phase 5.** Add the lane factory, the fan-out and join.
Acceptance: three lane outputs; the same on the other arm with no thinking
tokens.

**Step 6 — phase 6.** Reorganise into the seven files, add `lanes.py`
and `plugins.py`. Acceptance: the exit-code sequence in section 9.

**Step 7 — phase 7 (optional).** Regroup into `core/`, `rules/`,
`collect/`, `judge/`, `deliver/`, then add the retries, the ceiling, the gates, the
verifier and the blast radius. Acceptance: section 10's exit criteria.

**Built alongside, no key needed.** `tests/` drives every phase through
ADK's own loader and Runner with a fake model for `fake.*`, so the real
`build_model()` runs in every test. `scripts/ask.py` is the same Runner
shape as a one-turn command.

**Conventions kept across phases.** Tools return `{status: …}` and never
raise at the model; git runs read verbs only, with a timeout, and a failed
call is a named error; every string a model reads is capped with a named
cut; findings carry evidence; nothing writes into the repository under
review; a change that works on one arm is not finished.

---

## 12. Decisions taken, and what they trade

- **ADK 2.9.2 and `Workflow`, not the deprecated `SequentialAgent`,
  `ParallelAgent` and `LoopAgent`.** The graph primitive is what 2.x
  teaches; the older classes get one sentence in phase 4.
- **Copilot and Gemini from phase 1, Copilot first.** The talk is given on
  Copilot and the team runs on it, so it is the default arm. Only
  `config.py` names a provider, and every phase runs on both arms. A third
  arm would add a key and no lesson.
- **`output_schema` on both arms, no `PlanReActPlanner`.** ADK 2.9.2's
  LiteLLM wrapper maps a response schema to a JSON-schema response format,
  so Copilot returns the same typed dict.
- **A generated demo repository, not a real project.** No network, no
  waiting, and phase 6's fix-and-rerun moment is rehearsable: its two
  blockers, the key pair and the shell call, were found in all seven live
  Copilot runs.
- **Duplication over sharing.** Every phase folder is self-contained; only
  `.env` is shared. A copy of `tools.py` in each folder that uses one buys a
  folder that reads alone and a diff between two folders that is the lesson.
- **Folders, not stacked branches.** A branch per phase would make every
  phase switch a checkout and a server restart, and a phase 2 fix a rebase.
  Folders keep all seven phases in one `adk web .` dropdown, and a phase's
  lesson is `git diff --no-index` between neighbouring folders, not a commit.
- **Phase 7 is optional, and it regroups before it adds.** Six phases teach
  ADK; the seventh answers "how would this grow?". It regroups by
  dependency direction first, because each hardening item then lands in
  exactly one group, and that placement is the lesson.
- **Phase 7 after review: the request carries the retries, and the verifier
  runs before the fold.** ADK 2.9.2 reads `retry_options` off the request
  config on both arms, so one line covers them. After the fold, a refuted
  survivor took a gate's reading down with it; before it, the gates are
  never lost, at three verifier calls on the demo instead of one.
- **Phase 7 after a second review: the verifier is a graph, and the package
  root loads nothing.** One verifier per finding in a `Workflow` is the
  shape the lanes already teach. The root answers `agent` lazily, so
  `core/` imports with ADK absent, as phase 7 claims. A lane without
  evidence is skipped, never run over nothing, because "no findings" must
  not read as approval.
- **Phase 6 after phase 7's reviews: what was a fix went back.** A fix
  found in phase 7 that is not phase 7's lesson goes to the phase that
  introduced the code, so every phase reads as the previous one plus its
  lesson. What is phase 7's lesson, such as its lazy package root, stays.
- **Error handling from phase 4, after the Gemini run.** A spent free-tier
  key printed sixty lines of traceback. Phases 1 to 3 stay the smallest
  agents, so `on_model_error_callback` starts at phase 4: a failure becomes
  a sentence left under `temp:failure`, reviewers skip without evidence,
  and the verdict never approves what was not judged.
- **A fallback model, and a rehearsal script.** Both after the Gemini run.
  `REVIEW_FALLBACK_MODEL` puts a second model behind every role's first,
  through ADK's `FallbackModel`: a second quota, not a guarantee.
  `scripts/rehearse.py` runs every phase's demo line in order.
- **The hook on Copilot, live.** Phase 4 with a model that does not exist
  answered as designed. LiteLLM printed a debug banner with every error,
  so `litellm.suppress_debug_info = True` is set where the arm is built.
- **A command from phase 4, at the user's request.** Phases 4 and 5 each
  gained a `review.py` with an honest exit code; deciding in code stays
  phase 6's lesson. The package root drops `from . import agent` there,
  because `python -m` imports it before `main` reads `.env`.
- **`adk web`, looked at in a browser.** `adk web` uses a nested loader
  that lists any folder holding an `agent.py`, so phase 7's graph module is
  `judge/graph.py`, and a test asks the nested loader for the list.
- **A blast radius in phase 7, at the user's request.** Review depth should
  follow blast radius. It reads the syntax tree at the head revision, since
  a grep cannot tell an import from a comment, errs wide, and informs the
  lanes and the reader but never the verdict: an import graph cannot see a
  module loaded by name, a subprocess or a route.
- **The blast radius after four reviews.** Three findings were the radius
  reading narrow, which it must never do, so a tree it could not list
  makes every count a floor, and an import depends on every package on the
  way. Paths are flattened, because one holding newlines forged a heading
  in the prompt.
- **Grounding by whole lines of the finding's own file, at the
  user's request.** A quote grounds only as consecutive whole lines of its
  own file's hunks, so nothing around the diff can be quoted into a
  finding. Whitespace is ignored, because a Gemini lane lost the breaks;
  over six live runs, all thirty-seven lane quotes grounded.
- **A git call past its timeout is a named error.** Answered as empty, a
  timeout would read as an empty change, and a lane shown nothing finds
  nothing. `_git` raises an error naming the verb and the limit, and only
  the tools, the preflight and `collect_evidence` turn it into an envelope.
- **A git call that fails is a named error too.** Phases 6 and 7 approved
  a branch sharing no history with main and a partial clone whose diffs all
  failed. `_git` raises `GitError` for any exit code its caller did not
  name as an answer.
- **The demo repository and the fixtures are built from no one's git
  config.** A global `commit.gpgsign = true` failed them, so both run git
  with `GIT_CONFIG_GLOBAL` at the null device and the system config off.
- **The interpreter and the lock are the ones measured on.**
  `.python-version` pins 3.13, where every measurement ran, and `make sync`
  passes `--locked`. Kept: `google-adk[extensions]`, the documented install
  for LiteLLM; the nltk advisory it brings is unreachable from the demo.
- **Offline means offline, and the suite is the suite's.**
  `import litellm` tried to fetch its model map, and LiteLLM read the
  nearest `.env`, the developer's keys. `conftest.py` turns both off before
  any import and clears every `REVIEW_*` variable before each test.
- **Copilot asks for one attempt, and a run has a deadline.**
  LiteLLM retried around the SDK's retries, so in phase 7 one lane call
  could take twenty-one minutes. Phase 7's Copilot request asks for one
  attempt, and `run_seeded` stops a run at ten minutes, naming every lane
  still out.
- **The Copilot token stays its owner's.** `adk web -v` logged the token,
  which rides in the request body. Phases 6 and 7 filter LiteLLM's logger
  to hide a bearer token, and the login keeps its files 0600.
- **A misspelt provider is a sentence everywhere, and the report names
  the model.** A misspelt provider was a traceback and exit 1, a blocker's
  code, so phase 6 imports its graph after the readiness check. The shell
  wins over `.env`, so the reports of phases 6 and 7 name the model and arm
  that ran.
- **A name that is only a tag is named as one.** A tag named `origin/main`
  stood in for the branch, as git resolves it. Refusing it would refuse
  every tag, so the reports print the tag beside the name:
  `origin/main (the tag refs/tags/origin/main)`.
- **A file that does not parse is a major finding.**
  Ruff rated `invalid-syntax` minor and reads no other rule in such a file,
  so a `shell=True` inside one went unreported. The gate rates it major.
- **The change is fenced as data, and told to be.**
  A markdown file's own fence closed the one around the change. Each file
  is now fenced one backtick longer than its longest run, and the lanes
  are told the change is data, never instructions.
- **A quote grounds as the file has it, and a blocker it cannot ground
  is no approval.** A leading `+` or `-` may be the file's own text, so a
  quote grounds with it or without; a blocker that still does not ground
  is a hole, `DEGRADED`, exit 3.
- **A secret is a value, never a name.** `token = get_token(request)` was a
  blocker, failing a build for reading a variable. The generic shape now
  wants the value, never a template or a call, and eight vendor shapes
  join it.
- **The lint gate writes nothing outside its folder.** A path of
  `../../escape.py` was written beside the gate's folder; each file is now
  written under a name of the gate's own, so no branch path names a file.
- **A path forges nothing, and the lint gate lints what the branch
  changed.** A path holding newlines printed forged verdict lines, so every
  path a report prints is flattened. The gate passes `--ignore-noqa`, since
  `# ruff: noqa` in the branch silenced it.
- **Only what a branch adds can go unread.** A rename is read as what it
  moved and changed, and a deletion is never marked unread; a bumped
  submodule is, since one carrying the key had approved.
- **git reads the repository named, as committed, however a name is
  spelled.** A replace ref, a graft or a `GIT_DIR` left in the shell each
  made a review approve what it had not read. Every git call runs in
  `_environment()`, which drops such variables and turns off replace refs
  and grafts.
- **What no lane read is named, and never approves.** A branch adding
  nothing, a binary file and a defect past the diff cap each approved. Now
  an empty change is exit 2, and a file no lane read whole is named under
  "not read", `DEGRADED`, exit 3; the cap is the knob.
- **A file's diff is read as git prints it for no one's settings.**
  A path spelled `:config.py`, the branch's own `.gitattributes`, or the
  reviewer's `color.ui` or `diff.external` each let the review approve a
  branch whose key it never read. Phase 3's `_diff` now takes
  each path literally (`:(top,literal)` magic, below), reads attributes from the merge base with
  `--attr-source` (git 2.41, the stated minimum), and turns off colour,
  external diffs and text conversion.
- **A name that means two refs is refused.** Git prefers a tag to a
  branch of the same name, so a fork's tag `main` made the base the head
  and the review approved a change it had read none of. The preflight
  refuses a name that matches more than one full ref, naming both, and
  peels each with `^{commit}`. Phase 2 wrote it; later copies carry it.
- **A shallow clone is refused, never reviewed.** In a shallow clone
  `merge-base` can answer an older commit, and the review then read one of
  `main`'s changes as the branch's. The preflight asks
  `rev-parse --is-shallow-repository` first and refuses, naming
  `git fetch --unshallow`; a shallow clone that would have worked is
  refused too. Phase 7's `--all`, which needs no merge base, reviews one.
- **Nothing is fetched into a partial clone.** In a `--filter=blob:none`
  clone the review's read-only git calls fetched missing blobs, a write
  into the repository under review. Every git call now runs with
  `GIT_NO_LAZY_FETCH=1`; a diff the clone cannot read is exit 2.
- **A ruff that fails is the lint gate's hole too.** A ruff that could not
  run exits 2 with nothing on stdout, which the gate read as no findings.
  Any exit but 0 is now the gate's named reason, exit 3. A
  syntax error is a finding (`invalid-syntax`), not a failure.
- **A project's own rules, and profiles, at the user's request.** A rule
  is one self-contained class in phase 7's `rules/`, `check(path, line)`
  over each added line; a profile is a named list of rule ids, and
  `--profile` is the one choice. Nothing is read from the repository under
  review, which could otherwise switch its own secrets gate off. The
  built-in checks are rules by id too, so a profile can drop a lane. A
  rule that raises is a hole, exit 3; a broken rule or profile is exit 2
  before any model call.
- **A finding's evidence is cut where a person reads it.** A key on a
  minified line printed all 200,000 characters. The report of phases 6
  and 7 cuts evidence at 400 characters, after the scrub, so a cut never
  halves a credential past its pattern.
- **A renamed file is read as a rename in chat too.** `show_diff` never
  passed a rename's old path, so in chat a renamed file read as all lines
  added. The `changed_files` allowlist in state now maps each path to its
  old one, so no second listing is needed.
- **The default is every check, in code, at the user's request.** A
  hand-kept default list ran a new rule only once someone listed it. Now
  `default` is every built-in check and every rule in `rules/`, and the
  file holds only narrowings such as `gates-only`.
- **A rule of the payments project's own.** `money-in-cents` flags a name
  holding the word `cents` divided by a number. It reads tokens, not
  text, since a regex flagged comments, strings and the `Decimal` its own
  fix recommends. It finds the planted `report.py:5` and not
  `charge.py:19`, which `main` already had: a rule sees only added lines.
- **A path is the one file it names.** With `a` renamed to `b.py` beside a
  new `a/x.py`, `-- a b.py` matched the folder `a/`, and `b.py`'s diff
  carried `a/x.py`'s key. Each path is now `:(top,literal)` pathspec magic with
  what lies inside a folder of its name excluded, and git's pathspec variables are not
  passed on from the shell.
- **A cleanup pass, measured.** `money-in-cents` tokenized every line; a
  line without `cents` is now never tokenized, 487 ms to 12 ms on 21,477
  added lines. `no-print` reads tokens too, and both rules skip tests.
  Left for the next entry: `gates-only` loading the model stack, one git
  process per file, and `GIT_DIFF_OPTS` from the shell.
- **What git prints is git's, and a start costs what it uses.** The
  shell's and the person's git settings could strip context lines or hide
  every added line. `_environment` now drops every `GIT_*`, global and
  system config and attributes, and diffs are read through plumbing,
  `diff-tree -r -p`, which reads no display setting. `import litellm` cost
  about a second of every start, so only the Copilot arm imports it, when
  its model is built. Per-file git calls run eight at a time: `gates-only`
  on 224 files went from 5.75 s to 2.36 s.
- **The docs read against the code, and against each other.** Phase 6 ran
  its secrets gate after the lanes while its docs said before; it now runs
  first, and a test pins the order. ADK does accept `tools=` and
  `output_schema=` on one agent, so phase 4 keeps them apart for the job
  each does, not because ADK refuses.
- **What a live run showed the report got wrong.** The fold now keeps the
  most severe finding first and drops any whose quote overlaps one kept;
  it had shown `shell=True` twice. A lane's line number was the model's,
  wrong in 4 of 5, so a finding is now named at the line grounding finds.
  Under `--verify`, a lane finding that restates a gate's at least as
  severe is not asked; this narrows "the verifier runs before the fold"
  above.
- **The talk rehearsed on its arm, Copilot.** Every step ran as the talk
  expects, and the fix-and-rerun gave APPROVED, exit 0, three times of
  three. `gate_lint` said "no findings" when its findings had folded into a
  lane's blocker, so each source's section now names what it folded into.
- **Windows, audited and pinned.** At the user's request, the code was
  audited against Windows: git's timeout now stops the whole process tree,
  git and ruff are found by full path rather than the current directory,
  every pathspec is `top`, a UTF-16 `.env` is exit 2, and committed files
  use `\n`. CI (`.github/workflows/ci.yml`, and `azure-pipelines.yml` on
  Azure DevOps) runs the suite on Windows.
- **One config file for phase 7.** At the user's request, phase 7's
  profiles and review policy live in `config.toml` beside `review.py`, in
  `[review]`, `[lint]` and `[profiles]`. A flag still wins for one run.
  Provider, models and keys stay in `.env`; rules stay code in `rules/`.
- **Folding by the lines a finding sits on.** Folding by text alone let a
  minor quoting `return None` swallow a blocker ending in another
  `return None`, and the shell injection vanished from the report. Two
  findings now fold only when one's line span holds the other's.
- **A crash is a hole, never a verdict.** Python ends an uncaught
  exception with exit 1, the code for "a blocker was found". From phase 4,
  `main` wraps the command: an error nothing else names is one sentence
  and exit 3.
- **SOLID where a review found it wanting.** `main` ran every check inline
  and grew with each kind; it is `run_checks` now. The report loaded 155
  ADK modules for text; a layering test now holds `deliver/` to `core`.
  Rejected as more than they remove: typed records, one-implementation
  interfaces, and splitting `collect/git.py`.
- **Lint and CI, and two things measured and left.** Ruff families with
  no hit are on as free guards, BLE001 makes every broad `except` say why,
  and S607 holds the reviewer to full program paths. CI writes nothing,
  keeps no credentials and pins each action by commit. Left: an oauthlib
  advisory against OAuth server endpoints this code never serves, and the
  diff in the lane's system instruction, fenced as data.
- **What the lanes find, measured.** `scripts/measure.py` reviews the
  planted branch N times and reads each report as a person would, so a
  lane's recall is a number, not a hand count.
- **The tests lane asks what the change leaves untested.** Its role now
  asks first whether what the change adds is tested at all. On Copilot the
  untested function went from 2 of 5 runs to 5 of 5; a missing test stays
  minor.
- **Phases 6 and 7 on Gemini, and the free tier's day.** On a free-tier
  key, 503s and 429s ended lanes, each named, exit 3, and retries only
  spent the quota faster. One `--verify` run is half a free-tier day, so a
  Gemini rehearsal needs a billed key, and the talk runs on Copilot.
- **Leaner, with no name added.** A review kept only changes that delete,
  each validated before it landed. It found the redaction count read
  before `--verify`'s verifiers ran, missing what was hidden from them; it
  is read after them now.
- **An outside review checked claim by claim, three kept.** A quote that
  appears twice is now placed by the lane's line, not the first match.
  The lint gate splits lines as ruff does, not at a form feed or U+2028.
  The blast radius no longer takes a folder without `__init__.py` inside a
  package for an import root. Declined: a shared rate-limit gate, a cap by
  hunks, SARIF, and an ignore list for unread files.
- **The radius names what imports a file.** In 23 of 30 trees, over
  half the files reach over half the tree, so reach tells them apart poorly;
  the direct importers tell them apart in every tree. Each line names what
  imports a file and orders by direct importers, then reach.
- **What a review covers, and `.gitignore` left to git.** At the user's
  request: `--path` keeps a review to a folder, the rest named; `--all`
  diffs the head against git's empty tree, so every file reads as added;
  `--head` defaults to the branch checked out; with neither `--base` nor
  `--all` a terminal asks, and CI reviews against `main`, or `master`.
  `.gitignore` is left to git, which already keeps ignored files out of
  commits: a filter by it would have approved a force-added `.env` with a
  key.
- **The whole project, tried on this repository.** `--all` over this
  repository's own files found nothing real in the gates, since the gate reads
  no project's config; so `[lint]` gains `ignore`. With lanes, most files
  were cut at the cap and the run cost 80,000 tokens a lane, exit 3.
- **The whole project measured, and the lanes' wording kept.**
  `scripts/measure.py --all` named the planted defects about as often as
  the branch's own review, so no whole-project wording was written for the
  lanes. What fails is size: `--all` suits a project that fits the cap.
- **Leaner after the whole project.** A cleanup left every report
  byte-identical. The blast radius asks once per file whether it is a
  test, not once per file reached: `--all` over 4,340 files went from
  20.6 s to 7.4 s.
- **What the lanes read, capped in all.** Uncapped, `--all` over 4,826
  files sent each lane 14.9 MB of diffs. The block now stops at 250,000
  characters; a file past it is left out whole and named under "not read",
  and the blast radius beside it is cut at 20,000, widest first. Each
  verifier keeps the whole diff. Measured on Copilot, given only its
  finding's file, the changed files importing it and the changed tests, 6
  findings judged twice each way changed none, and saved 1,000 to 1,850
  tokens a run: the lanes found nothing in three changes of 34,000 to
  181,000 characters, so a large diff asked no verifier at all.
- **A single agent file against phase 6, measured.** One agent with a
  skill-file prompt, phase 3's read-only git tools and the same model at
  temperature zero, on Copilot. On the demo branch both found the same
  three defects, 5 runs each. The single agent file sent the AWS key to
  the model in all 5 runs and printed it in 4; on two bigger changes with
  four files cut at the diff cap it approved 6 of 6 runs without a word
  about the cut, where phase 6 named them and was degraded 4 of 4. The
  README's sentence on what ADK adds rests on this.
- **The question asked only where it is seen.** The question goes to
  stderr, but only stdin was checked, so with `2>/dev/null` at a terminal
  the command waited on a question no one saw. It is asked now only when
  both are the terminal; otherwise the change is reviewed against `main`,
  or `master`, as in CI. `/dev/tty` would serve both, and not Windows.
- **Nothing printed runs in a CI log.** Azure's agent runs `##vso[`
  anywhere in a log line and GitHub's runner `##[`, and phases 6 and 7
  printed the branch's paths and quotes as they stand. Each opener is now
  broken with a space across any non-ASCII run, `##vso [`, and a sentence
  on stderr is one line.
- **Lint reads in one batch.** One `git show` per file was 16.5 s of a
  4,826-file `--all` review; lint now reads through the blast radius's
  single `cat-file --batch`, in 0.16 s, the same text. Declined: an ignore
  list for unread files (the branch picks the names, so `*.png` would
  approve whatever it hid in one), SARIF and `-U<N>`.
- **`--all` diffs in one call.** Under `--all` every file is added, so one
  `diff-tree -p` splits safely at each line opening `diff --git`: 4,826
  files took 9.4 s one call a file and take 0.86 s, the same bytes. A
  branch is still diffed file by file.
- **Changed files fenced as code.** Named `a<!--.py` and `b-->.py`, two
  files hid every name between them on the changed line wherever the
  report renders as markdown, and two importers on the blast radius's.
  Each changed name is now a code span, and every `<!--` printed is
  broken, `<! --`, as a CI runner's opener is.
- **A standard library name stays the standard library's.** In a
  namespace package, a folder with no `__init__.py`, the blast radius read
  `import typing` as an import of the package's own `typing.py`: 81
  importers where 7 are real, at the head of the report. Such a name now
  lands only on a file at the top.
- **An instruction that is no string is refused.** ADK 2.9.2 writes the
  system instruction as a string, but the redaction plugin passed any other
  shape on unread; that is now `REDACTION_FAILED`, as a broken scrubber is.
- **No tests inside the phase folders.** The file budget is spent on the
  lesson; the offline suite lives in `tests/` at the root.
- **A failed lane is its own answer, never a retry.** An exception a lane
  let escape tore the whole graph down and ended in exit 1, the code for
  "findings found". `ReportProviderErrors` uses ADK's model-error hook to
  answer in the exception's place, so the lane ends with an error under
  its own name and the others finish. `REQUEST_TIMEOUT_S` makes a hung
  call a model error too. `retry_config` stays off: showing the failure is
  the lesson.
- **Deliberately left out of phase 6:** baselines and dismissals, SARIF
  and the scorecard, product features each more of the same shape; the
  token ceiling, `--verify`, retries set on the request and a project's
  own rules, which phase 7 adds; and `PlanReActPlanner`, which fails beside
  `output_schema`.
- **More checks through ruff, and three rules of the folder's own.** A rule
  is for what no tool checks, so `[lint]` now also selects complexity past
  ruff's own thresholds (C901; PLR0911, PLR0912, PLR0913 and PLR0915), blocking calls in async
  code, a task created and dropped, a debugger call and commented-out code,
  none of which fires on the demo branch; `rules/` gains text that tries to
  instruct the reviewing model, a test patching a private name and a test
  reaching the network, each a line rule with its own test. The lint gate
  tiers a code by the longest key it begins with inside its own family,
  keyed by ruff's own prefixes and codes, so `SIM` never inherits `S` and
  `C90` never reaches `C416`; an unused import or local is minor; and a
  finding ruff offers no fix for names its code's or its family's sentence
  before the pointer, "see ruff rule", it always gave.
- **Tree rules.** A line rule cannot say that a file must exist, a module
  define a name, a class derive from a parent or a function take a parameter,
  so a second kind reads the head: the listing the blast radius already makes,
  and its modules, parsed once for both (measured, a second parse had nearly
  doubled the head read's time), held through the gates (measured at about
  thirty times the source's bytes) and dropped before the model calls. Four
  shipped, expectations in their own constants, the payments project's own: a
  review of another repository reports them missing until the constants are
  edited or a profile leaves them off. A file not read whole is a hole for a
  rule that asks for it by name, and a floor, said in the report, for a rule
  over the whole tree; a tree that could not be listed is a hole for every
  tree rule.

---

## 13. Presenter's checklist

Before the talk: `uv sync`, `.env` on Copilot, the Copilot login once, the
demo repository built fresh, old chats deleted (`phase_*/.adk`), the opening
phase 6 command run once (and phase 1 on Gemini, if the switch will be
shown), `adk web .` open in a browser tab with its side panel open, never
with `-v` on a shared screen, and the chat messages ready to paste:
`scripts/rehearse.py --dry-run` prints the review message with the real path.

During: the review message in every phase from 2 on, plus phase 2's missing
branch and phase 3's two diff requests; the event cards after every chat
run; the fix-and-rerun in phase 6; the spend line last. Phase 7 is a
three-minute pointer: the layering test first, then `--verify`, then
`--max-tokens`, then `--profile gates-only`.
