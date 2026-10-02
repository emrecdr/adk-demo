# Phase 5 — parallel lanes

Phase 4 with the reviewer split into three. Security, tests and complexity
judge the same diff at once, a join waits for all of them, and a verdict
agent writes them up. Each lane comes from one factory over a three-line
table, so adding a lane is a row, not a file, and the provider chosen in
phase 1 is still the only provider-specific code.

## What changed since phase 4

- **Changed: `agent.py`.** `LANES` is a table of `(name, role, thinking budget)`;
  `build_lane` turns a row into an `LlmAgent` named `lane_<name>` with the
  shared `{diff}`, the shared `Review` schema, a severity scale spelled out in
  the prompt, `include_contents="none"`, temperature zero, a planner, and
  `output_key="lane_<name>"`, the failure hook and the evidence guard.
  `join = JoinNode(name="join_lanes")` waits for every lane. `verdict` reads
  `{lane_security?}`, `{lane_tests?}` and `{lane_complexity?}` from state —
  optional, so a lane that wrote nothing leaves an empty section instead of
  failing the verdict too (a provider error answers in the lane's schema) — and writes markdown, told to say which lane
  failed or did not look and never to approve on it. The edge is
  `("START", collector, lanes, join, verdict)`: the inner tuple is the
  fan-out. `max_concurrency=3` is what a free-tier quota tolerates.
- **Changed: `config.py`.** Gains `lane_planner(thinking_budget)`: a
  `BuiltInPlanner` with that thinking budget on Gemini, `None` on Copilot.
- **Changed: `review.py`.** Prints the verdict and takes its first line as
  the exit code: 0 for APPROVED, 1 for REQUEST CHANGES. That is the model's
  word, relayed; phase 6 decides in code against a bar instead. An agent that
  failed is exit 3 whatever the verdict says, and so is a verdict that
  names neither word: the command does not guess.
- Unchanged: `__init__.py`, `schemas.py`, `tools.py`, `callbacks.py`.

## Run it

```bash
uv run adk run phase_5_parallel_lanes
```

```
review <demo repo>, branch feature/payments against main
```

`<demo repo>` is the path `scripts/make_demo_repo.py` printed. Sent in
`uv run adk web .` instead, the Traces view shows three lane calls overlapping in time,
the join firing once, and the verdict citing all three lanes. Then set `REVIEW_PROVIDER=gemini` in `.env`,
restart, and send the same message: the same graph, the same typed findings,
and thinking tokens in the usage line, which the Copilot run had none of,
because only Gemini has a budget to spend.

The same review as a command:

```bash
uv run python -m phase_5_parallel_lanes.review --head feature/payments   # the demo repository against main
```

Expect the verdict on stdout and exit 1: on the planted branch it says
REQUEST CHANGES.

## What to notice

- Fan-out is an inner tuple in the edge; `JoinNode` waits for every branch;
  `max_concurrency` is the knob a shared key needs.
- The model is chosen per agent. Every lane calls `build_model()` here; that
  is the line that would change to put a cheap model on the mechanical stages
  and the expensive one on the judgement.
- `BuiltInPlanner` is configuration only: it sets a thinking budget on the
  request, adds no prompt text, and only Gemini honours it. ADK's alternative
  for other models is `PlanReActPlanner`, prompt engineering that runs
  anywhere but collides with `output_schema`. This demo keeps the schema and says
  plainly that the reasoning lever is absent on Copilot.
- **Nothing here redacts anything.** Measured on Copilot, this phase printed
  the planted AWS key back in its verdict. Leave that on the screen for a
  moment; phase 6 is where it stops, and the audience has just seen why.
