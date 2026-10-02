---
name: review-a-branch
description: Run this repository's own reviewer, phase 7, on a git repository and branch and read its report — model-free with --profile gates-only, or with the lanes when a provider is configured — and explain the exit code. Use when asked to review a branch, try the reviewer, or see what the gates and rules find.
---

# Review a branch with phase 7

The reviewer is a command: `python -m phase_7_hardened.review [repo] [--head B] [--base main | --all] [--path DIR]
[--fail-on …] [--verify | --no-verify] [--max-tokens N] [--profile NAME]`. With no `repo` it reviews the demo
repository that `scripts/make_demo_repo.py` builds in the temp folder.

1. Without a model, which needs no key and is safe anywhere:
   `uv run python -m phase_7_hardened.review <repo> --head <branch> --base main --profile gates-only`. The gates
   (secrets, ruff) and every rule in `phase_7_hardened/rules/` run; the lanes do not. In a pipeline name `--head`,
   since the checkout is a detached commit, and fetch the base branch with its history, or review the whole head
   with `--all`.
2. With the lanes, only when asked and when `.env` names a ready arm (`REVIEW_PROVIDER=copilot` after
   `scripts/copilot_login.py`, or `gemini` with `GOOGLE_API_KEY`): drop `--profile`. Never print `.env` or a key;
   the report names the arm and the model that ran.
3. Read the exit code: 0 approved; 1 a finding at or above `--fail-on` (`blocker` by default); 2 a usage error
   before any model call, such as a branch that adds nothing, an arm that is not ready, or a `config.toml` or
   profile that cannot run; 3 a hole — a gate, lane or rule failed, a tree rule could not look, or a changed file no
   lane read whole — which must never be read as "nothing found".
4. The report lists findings by source (`gate_secrets`, `gate_rules`, `gate_lint`, then the lanes), the blast
   radius of each changed file, what was not read, and what the run cost. Quote its lines when you report, rather
   than paraphrasing them.
