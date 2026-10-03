---
name: new-lane
description: Add a reviewing lane to the reviewer — one row in the lane table of phases 6 and 7 (a name, a role sentence, a thinking budget) — and bring the tests and the docs along; the fan-out, the chat verdict's sections, the report and phase 7's lane.<name> check all follow from the table. Use when asked to make the reviewer judge a new concern, such as documentation or performance.
---

# Add a lane to the reviewer

A lane is one row of `LANES`: `("name", "You judge …", thinking_budget)`. Phase 5 introduced the table with the talk's
three lanes (`phase_5_parallel_lanes/agent.py`), and three is its lesson; the reviewer the team runs is phase 6 and its
copy in phase 7, so a team's lane goes into `phase_6_reviewer/lanes.py` and `phase_7_hardened/judge/lanes.py`, the same
row in both. Nothing else names the lanes: `LANE_NAMES`, the fan-out, `state_key` (`lane_<name>`), the chat verdict's
sections, `SOURCES` and the report, and phase 7's `lane.<name>` check id all read the table.

1. Add the row to both files: a lowercase name, a role of one sentence that starts "You judge", and a budget — a Gemini
   thinking budget, which Copilot ignores. Say in phase 6's README, under `What changed since phase 5`, that the lane is
   the team's addition, since the diff between phases 5 and 6 now shows it.
2. Profiles in `phase_7_hardened/config.toml`: `default` runs every check, so the lane runs without an entry; a profile
   that lists lanes must name `lane.<name>`; `gates-only` lists none and stays as it is.
3. Tests: `tests/test_reviewer.py` and `tests/test_hardened.py` name the three lanes and count them in places; run them,
   and extend each assertion the new lane breaks rather than loosening it.
4. Docs: a case-insensitive search for `three lanes`, `lane.security` and `security, tests, complexity` finds every
   place that names or counts the lanes, the comment over `[profiles]` in `phase_7_hardened/config.toml` and the
   docstrings of phases 6 and 7 among them. Update each, except phase 5, where three is the lesson, and a measured
   number, which is history. The deck says three as well: report that to the presenter, and do not touch
   `docs/presentation/`.
5. Run the whole suite and the lint. Measure the lane live only when asked — `uv run python scripts/measure.py --runs 5`
   calls a provider — and record a decision it settles in §12.
