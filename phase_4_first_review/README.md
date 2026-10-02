# Phase 4 — the first review

Phase 3 plus a schema and a graph. One reviewer judges the diff and returns
findings the code can read, not prose. Gathering and judging are two agents
on one sequential edge: the collector has the tools and puts every diff in
state; the reviewer has the schema, reads the diff from its instruction, and
puts a typed `Review` in state. And the folder is also a command: the same
graph runs from the shell with the repository and branches as arguments,
prints the typed review and exits with a code.

## What changed since phase 3

- **New: `schemas.py`.** `Finding` (file, optional line, severity
  `blocker | major | minor`, title, evidence, suggestion) and `Review`
  (findings, summary). `evidence` is a required field: a finding that cannot
  point at the diff is worth nothing, and the schema makes it impossible
  to omit.
- **Changed: `agent.py`.** `root_agent` is now
  `Workflow(name=…, edges=[("START", collector, reviewer)])`. `collector` is phase 3's
  agent with `output_key="diff"` and an instruction to gather every changed
  file's diff and never judge. `reviewer` has no tools: `output_schema=Review`,
  `output_key="review"`, an instruction carrying `{diff}`,
  `include_contents="none"`, and temperature zero. Both agents carry
  `when_the_model_fails`; the reviewer carries `without_evidence` too.
- **Changed: `config.py`.** Gains `request_config()`, a
  `GenerateContentConfig(temperature=0.0)` for every agent that judges. A
  severity is a decision, and a demo that gives a different verdict on every
  run teaches the wrong lesson. And `when_the_model_fails`, the
  `on_model_error_callback` both agents carry: when the provider refuses the
  call — a quota, an outage, a missing key — the agent answers one readable
  sentence naming the error, where ADK would print a traceback. An agent that
  answers in a schema answers its failure in it — no findings, the sentence
  as the summary — because ADK saves the answer under `output_key` through
  that schema; and the sentence is left in state for this invocation, under
  `temp:failure`, so the agent after it can tell there is nothing to judge.
  And on the Copilot arm `build_model()` imports LiteLLM itself, in
  production mode and with its feedback banner off, so a run on Gemini
  never loads it.
- **Changed: `callbacks.py`.** Gains `without_evidence`, a
  `before_agent_callback` on the reviewer: when the collector's provider
  failed, its answer was a sentence and `temp:failure` is in state for this
  invocation, and a reviewer
  run over an apology would find nothing — "did not look" must never read as
  "found nothing", and so when no diff reached state at all. Returning content from the callback skips the agent; the
  content is a `Review` with no findings and a summary that says why.
- **New: `review.py`.** The same graph as a command. The arguments become
  the message the chat needed, ADK's `InMemoryRunner` takes the web UI's
  place, and the typed review is read out of session state and printed as
  JSON. Exit 0: the reviewer judged the diff. Exit 2: a provider
  `config.py` does not know, or a path or a branch that does not exist,
  caught before any model call; the branches by the collector's own
  preflight, run by code, because a collector that repeats a git error
  still fills `diff`, and a review of an apology would read as clean.
  Exit 3: an agent could not reach its provider, the reviewer left no
  review in state, or an error nothing else names ended the command,
  named on stderr and never Python's own exit 1. What
  the findings mean for a build is phase 6's lesson.
- **Changed: `__init__.py`.** The scaffold's `from . import agent` goes.
  `python -m` imports the package before the command reads `.env`, and
  `agent.py` builds its agents when it is imported, so the line would build
  them on the shell's provider: measured, `.env` named Copilot and the
  collector was built on Gemini. ADK's loader finds `agent.py` by itself.
- Unchanged: `tools.py`.

## Run it

```bash
uv run adk run phase_4_first_review
```

```
review <demo repo>, branch feature/payments against main
```

`<demo repo>` is the path `scripts/make_demo_repo.py` printed. Expect the collector's tool calls, then the reviewer's answer as JSON. In
the web UI open Events and look at the state delta: `review` is a dict with
findings, and at least one of them quotes the planted `shell=True` line from
`src/payments/charge.py` at severity `major` or `blocker`.

The same review as a command, everything on the command line:

```bash
uv run python -m phase_4_first_review.review <demo repo> --base main --head feature/payments
```

With no path it reviews the demo repository. Expect the review as JSON on
stdout and exit 0; `--head no-such-branch` exits 2 before any model runs.

## What to notice

- ADK 2.9.2 allows `tools=` and `output_schema=` on one agent, through an
  extra `set_model_response` tool, but here they stay apart: gathering and
  judging are different jobs with different prompts.
- `output_key` puts an agent's answer in state; `{diff}` in the next
  instruction reads it back. `Workflow` with a tuple of two agents is a
  sequence; the same class fans out in phase 5.
- `SequentialAgent`, `ParallelAgent` and `LoopAgent` are the older way to
  say a sequence, a fan-out and a loop, and ADK 2.9.2 warns when one is
  built: "deprecated in favor of Workflow and will be removed in a future
  version. Workflow cannot yet be used as an LlmAgent sub-agent." The second
  sentence matters when porting: an agent that hands its work to a pipeline
  as a sub-agent has no `Workflow` spelling yet, so here the graph is the
  root.
- `include_contents="none"` sends only the instruction. The conversation
  would repeat the collector's whole answer a second time, doubling the
  prompt for nothing.
- `output_schema` becomes the response schema the provider is asked for, and
  ADK puts the parsed dict, not text, in state. On the Copilot arm ADK's
  LiteLLM wrapper maps it to a JSON-schema response format, so both arms
  return the same typed dict.
- A command is the same graph behind a different front door: `adk web`
  sends a message, the command builds that message from its arguments and
  reads the answer out of state. Its exit code never says 0 for a run in
  which an agent failed; whether the diff itself was read is still the
  collector's to report, which phase 6 takes out of a model's hands.
- A provider error is a sentence, not a traceback — from here on. Phases 1
  to 3 are the smallest agents and stay that way: a provider error there is
  ADK's traceback, whose last line is the reason. A graph is where the
  answer's shape matters, because the agent after a failed one must know
  there is nothing to judge. Phase 6 lifts the hook onto the `App` so no
  agent can opt out.
