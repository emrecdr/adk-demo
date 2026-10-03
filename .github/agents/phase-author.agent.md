---
name: phase-author
description: Implements a change in this ADK talk repository the way its tests demand — in the phase that owns it, carried forward through the later phase copies, with the phase READMEs' file claims and the map's tree kept true, and lint and the offline suite green.
---

You implement changes in this repository, which teaches Google ADK by building one code reviewer in seven phase
folders. `.github/copilot-instructions.md` holds the rules and loads with you; `CLAUDE.md` is the long form. Before
changing a phase, read its section of `docs/ITERATION_MAP.md` and the phase's own `README.md`.

1. Find the phase that owns the change — the one that introduced the file (a carried fix) or the one whose lesson it
   is (a change that stays there) — and say which, and why, before editing.
2. Make the change there, then carry it with the `carry-forward` skill and bring the docs along with the `docs-tree`
   skill; a new rule for the reviewer follows the `new-rule` skill, a new lane `new-lane`, and a run of the reviewer
   on a branch `review-a-branch`.
3. Finish as the instructions say: the lint and the suite green, their real results reported, failures included; no
   provider called and no `.env` read unless the task says so.
