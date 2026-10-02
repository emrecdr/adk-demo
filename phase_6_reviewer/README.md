# Phase 6 — the reviewer

Phase 5's command, rebuilt so a team can trust its exit code on any local
branch, with the whole architecture visible in seven files:
evidence is gathered in Python before any model runs, lanes only judge, and
code, not a model, decides the verdict and the exit code. Three plugins on
the `App` redact secrets from everything a model sees, count what a run cost,
and turn a provider error into the failing lane's own answer;
a deterministic gate finds the secrets the redaction then hides from the
lanes. The chat shape still works: `adk web` runs phase 6 like phase 5, with
the plugins attached.

## What changed since phase 5

New: `lanes.py`, `plugins.py`. Changed: `tools.py`, `config.py`, `agent.py`,
`review.py`. Unchanged: `__init__.py`. Gone: `callbacks.py`, `schemas.py`. The
guardrail moved into `tools.py` and the schema into `lanes.py`, so the table
reads as a merge as much as an extension.

| File | Holds | Since phase 5 |
|---|---|---|
| `tools.py` | `_git`, `inspect_repository`, `changed_files`, `show_diff`, the `only_changed_paths` guardrail, and `collect_evidence(repo, base, head)`: the same git calls run deterministically, returning the preflight, every file with its whole diff, and the rendered block the lanes read | absorbs the guardrail from `callbacks.py`; `_diff` returns the diff with `\n` its only line break (`_readable`); gains `collect_evidence` |
| `lanes.py` | `Finding` and `Review`, the `LANES` table, `state_key(name)` (the one place `lane_` is spelled), `build_lane`, `without_evidence` (a lane's skip when nothing was gathered), and `lane_review(state, name, missing)`: the dict ADK left in state validated back into a `Review`, or `missing`, the named reason it could not be | absorbs `schemas.py`, the lane half of `agent.py` and `without_evidence` from `callbacks.py` |
| `plugins.py` | `RedactSecretsPlugin` (scrubs known secret shapes from every tool result and every outgoing request; fail-closed), `UsageLedger` (model calls and tokens per agent), and `scan_secrets`, the gate: every known secret shape on an added line of each file's whole diff, with its line number, and `ReportProviderErrors`: the failure hook the phases before carried per agent, once, on the `App` — a lane answers nothing, so its key is a hole the command names; the intake or the verdict answers the sentence, as before | new |
| `config.py` | `provider()` validated once, `model_name` and `serving()` (the model and arm the report names), `build_model`, `lane_planner`, `request_config` (temperature zero and `REQUEST_TIMEOUT_S`, the deadline on every judging call, both arms), `copilot_token`, a log filter that hides a bearer token, and `require_ready()`: why the chosen arm cannot run, or `None`; called by the CLI, never at import | gains `provider`, `model_name`, `serving`, the deadline, `copilot_token`, the token filter and `require_ready`; the failure hook leaves for `plugins.py` |
| `agent.py` | `build_workflow(chat=)`, `build_app(chat=)` owning the graph and the plugin roster, `app`, `root_agent` | phase 5's `collector` and `verdict` become `_intake()` and `_verdict()`, built per graph because an agent object belongs to one parent; the graph is built by a function, under an `App` |
| `review.py` | the CLI | phase 5's command, rebuilt: evidence by code before any model runs, and the verdict and the exit code decided in code |
| `__init__.py` | nothing imported, so the command reads `.env` before any agent is built | unchanged |

## Run it

```bash
uv run python scripts/make_demo_repo.py                          # once
uv run python -m phase_6_reviewer.review --head feature/payments   # the demo repository against main; the exit code is the verdict
echo $?                                                          # 1: the key pair is two gate blockers, the shell=True a lane blocker
uv run python scripts/make_demo_repo.py --fix                    # the two fixes committed on the branch
uv run python -m phase_6_reviewer.review --head feature/payments   # APPROVED, exit 0
uv run python -m phase_6_reviewer.review /path/to/any/repo --base main --head my-branch
```

Chat still works: `uv run adk web .` and pick `phase_6_reviewer`, or
`uv run python scripts/ask.py phase_6_reviewer "review <demo repo>, branch feature/payments against main"`,
where `<demo repo>` is the path `scripts/make_demo_repo.py` printed.

Exit codes: 0 approved; 1 a finding at or above `--fail-on` (default
`blocker`: majors and minors stay in the report for a person); 2 usage (the arm is not ready, the repository or a branch does
not exist, or the branch adds nothing); 3 degraded (a lane failed, a file no lane read whole, a
finding at the bar no quote bears out, or an error nothing else names: each is named with the reason, what finished
is still reported, and a hole never approves).

One run on the planted branch, on the Copilot arm, ended like this, trimmed to
one line a finding (each also carries its evidence and fix) and the spend line's
total (a row per lane follows it). A lane's titles, how many findings are dropped
and how many folded are the model's doing and vary between runs; the gate's two
lines and the redaction count do not, and a lane's line is where its quote starts:

```
### gate_secrets
- **blocker** hard-coded credential (aws_access_key_id) (src/payments/config.py:4)
- **blocker** hard-coded credential (aws_secret_access_key) (src/payments/config.py:5)
### lane_security
- **blocker** Command injection vulnerability via unsanitized printer name (src/payments/charge.py:27)
…
- findings dropped for evidence not in the diff: 0
- duplicates across lanes folded into one finding: 2
- secrets redacted before any model call: 6
- spend: 3 model call(s) completed of 3 attempted, 3,806 tokens
```

## What the CLI does, in order

1. Loads the central `.env` by path (no ADK loader runs here) and checks the
   arm is ready before anything is spent, so a typo in `.env` is a sentence
   and exit 2, never a traceback from inside the run.
2. `collect_evidence` runs git in plain Python. No model has been called. The
   secrets gate reads every file's whole diff here, by code. Each diff has
   `\n` as its only line break: a lone `\r`, a form feed or U+2028 is shown as
   its escape, since one hid the key after it from the gate. A branch that
   adds nothing is "no change to review", exit 2. A file no lane can read
   whole — binary, a submodule, or cut at the 4,000-character cap — is kept
   and marked; a deleted file never is, and a rename reads as what it moved
   and changed.
3. Session state is seeded with the evidence and the lanes-only graph runs
   under the `App` that carries the three plugins, through an `InMemoryRunner`.
4. Each lane's `Review` is read back from state. A finding whose evidence is
   not whole lines, in order, of its own file's diff as the lane saw it
   (markers stripped, secrets redacted, whatever whitespace joined the
   lines) is dropped and named; one kept is named at the line its quote
   starts, read off the diff, never at the model's. The gate's findings join them. Two
   findings on one file, one's lines holding the other's (or, where the diff
   leaves either unplaced, one quote containing the other), from any lane or the
   gate, are folded into one and counted. A lane that failed — its provider raised or
   timed out, or the redaction plugin refused the call — ended as its own
   error event, so the others finished regardless; it is named with the
   reason. A failed lane, a file no lane read whole, or a finding at the
   `--fail-on` bar whose quote the diff does not bear out is a hole: the run
   is `DEGRADED`, exit 3, never approved. The verdict and the exit code are
   computed here.
5. A markdown report: preflight and the model that ran, each file not read and
   why, verdict, findings grouped by source with each quote cut at 400
   characters, the counters (printed even at zero), and what the run cost.

## What to notice

- The order is the architecture: deterministic evidence first, model
  judgement second, deterministic decision last. A model never decides
  whether the build passes.
- A callback is per agent and is where "this tool needs an allowlist"
  belongs. A plugin is registered once on the `App` and no agent can opt out,
  which is where "we never send a credential to a provider" and "we always
  know what a run cost" belong.
- The gate exists because of a measurement: with the redaction plugin on, no
  lane reported the AWS key, because no lane ever saw it. A secret must be
  found by code, from the diff, before any model runs. The report shows the
  gate's finding and how many secrets the plugin redacted, and never prints
  the secret itself.
- The change is the branch's own text: each lane is told it is data to judge,
  never instructions to follow, and it is fenced longer than any run of
  backticks in it, so no file can close the fence it is shown in.
- The report's paths and quotes are the branch's text: each is one line,
  escapes out, the changed files and the quotes fenced as code, and a CI
  runner's command opener (`##vso[`, `##[`) and an HTML comment's (`<!--`)
  are broken with a space.
- Two shapes are two graphs. `output_key` writes unconditionally, so an
  intake agent run over seeded evidence would replace it with whatever it
  gathered itself; the CLI's graph is the lanes and the join and nothing else.
- Both `root_agent` and `app` are exported. ADK's loader looks for `app`
  first; a bare `root_agent` would be wrapped in an `App` without the
  plugins — an easy bug to ship.
- `require_ready` is called by the CLI once, never at import and never
  inside the graph builder.
- A failed lane is its own answer. ADK's model-error hook lets a plugin
  return a response in the exception's place, so the lane ends with an error
  event under its name and the other lanes finish by construction; measured
  before the plugin, the exception tore the graph down and a sibling in
  flight was lost. The graphs before carried that hook on each agent; the plugin
  is the same hook once, on the `App`, and it answers by what the agent
  answers in: a lane answers in a schema, so it answers nothing and its key
  stays a hole for the code that decides — a review with no findings would
  read as an approval — while the intake or the verdict answers the sentence. A hung call is bounded at the model boundary:
  `REQUEST_TIMEOUT_S` rides on every lane's and the verdict's request, on both
  arms, and arrives the same way. In chat the verdict agent reads the lanes as optional
  placeholders (`{lane_tests?}`), so it writes the verdict from the lanes
  that finished and says which one did not; measured without the `?`, it
  raised on the missing key and `adk web` showed a traceback after all. And
  when the intake itself fails, no lane runs: each answers its own schema
  with no findings and a summary saying nothing was gathered, and the
  verdict is told never to approve on that — "did not look" must never
  read as "found nothing".
