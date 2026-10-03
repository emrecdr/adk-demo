---
name: new-rule
description: Add a project rule to phase 7's rules folder — a Rule over the added lines, a FileRule over each changed file, or a TreeRule over the head's tree — with its tests, its place in config.toml's gates-only profile and the docs, in the shape this repository uses. Use when asked to make the reviewer flag something new by code rather than by a model.
---

# Add a project rule to phase 7

The shape of a rule — the three kinds, the constants it names, what it may import — is in
`.github/instructions/phase-7.instructions.md`, which loads with any file under `phase_7_hardened/`. The procedure:

1. Read `phase_7_hardened/rules/README.md` — five minutes, one example of each kind — and copy
   `phase_7_hardened/rules/_template.py` under the rule's own name (discovery leaves `_`-named files aside, so
   the template never runs and the copy runs at once), then decide the kind: a `Rule` when one added line answers the
   question (`tokens(line)` from `phase_7_hardened/core/rules.py` reads it as Python does, so a word in a comment or
   a string is not code); a `FileRule` when the answer needs the file — a sentence wrapped over lines, a decorator
   and its definition, a function's length — through `file.lines`, `file.added` and `file.module`; a `TreeRule`
   when it needs the head's paths or every module. The three shipped shapes are `no_print.py`,
   `reviewer_instructions.py` and `required_paths.py`.
2. Keep the rule's expectations as constants at the top of its file, as `REQUIRED` is in `required_paths.py`.
   Nothing registers it: discovery finds it.
3. Add its id to `gates-only` in `phase_7_hardened/config.toml`; `default` needs no entry.
4. Try it alone, no model and no key: `uv run python -m phase_7_hardened.review --base main --check <id>` on the
   demo repository or any other. Then test it in `tests/test_hardened.py` beside the other rules' tests
   (`TestRulesAndProfiles`, `TestTreeRules`, `TestTheRuleKinds`): what it flags and what it leaves alone through
   `lines_hit(rule, path, text)`, that `self_check(rule)` from `phase_7_hardened.rules` is empty, and a run on the
   demo repository with `--profile gates-only` when the planted branch should trip it.
5. Draw the file in the map's §3 tree, mention the rule where `phase_7_hardened/README.md` describes the rules,
   check `uv run python -m phase_7_hardened.review --list-rules` shows it with its kind and its profiles, and run
   `uv run pytest -q tests/test_docs.py tests/test_hardened.py tests/test_layering.py`, then the whole suite and the
   lint.
