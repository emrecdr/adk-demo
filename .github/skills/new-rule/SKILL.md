---
name: new-rule
description: Add a project rule to phase 7's rules folder — a Rule over the added lines or a TreeRule over the head's tree — with its test, its place in config.toml's gates-only profile and the docs, in the shape this repository uses. Use when asked to make the reviewer flag something new by code rather than by a model.
---

# Add a project rule to phase 7

The shape of a rule — what it subclasses, the constants it names, what it may import — is in
`.github/instructions/phase-7.instructions.md`, which loads with any file under `phase_7_hardened/`. The procedure:

1. Read the two examples it names, then decide the kind: a `Rule` when one added line answers the question
   (`tokens(line)` from `phase_7_hardened/core/rules.py` reads it as Python does, so a word in a comment or a string
   is not code), a `TreeRule` when it needs the head's paths or parsed modules.
2. Write the rule as one new file in `phase_7_hardened/rules/`, its expectations as constants at the top, as
   `REQUIRED` is in `required_paths.py`. Nothing registers it: discovery finds it.
3. Add its id to `gates-only` in `phase_7_hardened/config.toml`; `default` needs no entry.
4. Test it in `tests/test_hardened.py` beside the other rules' tests (`TestRulesAndProfiles`, `TestTreeRules`): what
   it flags, what it leaves alone (a comment, a string, a test file where that matters), that `_fires_on_itself` finds
   nothing in its own source, and a run on the demo repository with `--profile gates-only` when the planted branch
   should trip it.
5. Draw the file in the map's §3 tree, mention the rule where `phase_7_hardened/README.md` describes the rules, and
   run `uv run pytest -q tests/test_docs.py tests/test_hardened.py tests/test_layering.py`, then the whole suite
   and the lint.
