---
name: carry-forward
description: Carry a fix made in one phase folder into every later phase that still carries the same file, keep each phase README's New/Changed/Unchanged claims true, and prove with git diff --no-index that each phase's diff is still only its lesson. Use whenever a file that several phases copy is changed.
---

# Carry a fix forward through the phase copies

Phase N is a copy of phase N-1 plus one layer, so a file often lives in several phases. Which phase a change belongs
to is `.github/copilot-instructions.md`'s rule; its history is ITERATION_MAP §12, "Phase 6 after phase 7's reviews".

1. Find where the file lives: `ls phase_*/<file>`. Phase 7 regrouped phase 6 by dependency direction: the table under
   "What changed since phase 6" in `phase_7_hardened/README.md` says where each module went.
2. Make the fix in the first phase that has the code. Apply the same change to each later phase that carries it;
   where a later phase changed the surrounding code, port the fix by hand and say so.
3. Check each boundary: `git diff --no-index -- phase_3_changed_files phase_4_first_review`, and so on up to phase
   7, must show only that phase's lesson. A fix that appears in a diff between neighbours was not carried.
4. Keep the READMEs true with the `docs-tree` skill: a file now `Changed:` in phase N+1 that was `Unchanged:` is
   reclassified, and the other way round.
5. Run `uv run pytest -q tests/test_docs.py`, then the whole suite and the lint.
