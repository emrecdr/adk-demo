---
applyTo: "**/*.md"
---

# Docs

- The docs are tested (`tests/test_docs.py`). `docs/ITERATION_MAP.md` §3 draws every tracked or
  untracked-but-not-ignored file and nothing else: one `├── name` or `└── name` a line, a folder's name ending in
  `/`, four columns of indentation a level, an optional `# comment` after the name; `uv.lock` and `.gitignore` are
  left out, and `.env` is drawn although git ignores it. A name may not hold a space. Add, remove or rename a file,
  and the tree and every guide that names it change in the same change.
- Each `phase_*/README.md` classifies every `*.py` directly in its folder against the previous phase in sentences
  like ``Changed: `agent.py`, `review.py`.`` — `New:`, `Changed:`, `Unchanged:`, `Gone:` or `Moved:`, backticked
  names, a period at the end, each file exactly once. The claims are checked against the bytes.
- A phase README has `## What changed since phase <n-1>` (phase 1: `## What is here`), `## Run it` and
  `## What to notice`, in that order, and may add one section of its own; `Run it` carries the phase's demo line as
  `scripts/rehearse.py` runs it.
- `docs/ITERATION_MAP.md`'s sections are fixed: what is taught, the iteration-map slide, the tree, one
  `## <section>. Phase <n> — ` section per phase folder, the plan, §12 the decisions, §13 the presenter's checklist. A
  §12 entry is one bullet, `- **What was decided.** why, and the measurement that settled it (arm, model, runs)`; a
  measured number there is history and stays.
- No dates (nothing here is a changelog) and no counts of the repository's current state: not how many tests, how
  long the suite takes, how many flags or example runs. Plain prose that says why, kept short; every claim about
  the code must be true of the code as it is.
- `README.md` is how to run the demo; `CLAUDE.md` and `.github/copilot-instructions.md` are the assistants' guides
  and say the same things: a rule that changes in one changes in the other. Every guide — `README.md`, `CLAUDE.md`,
  `phase_7_hardened/rules/README.md` and every Markdown file under `.github/` — names only paths the working tree
  has: a backticked path with a folder in it that no checkout holds fails `tests/test_docs.py` (`.adk/session.db`,
  written when `adk web` runs, is the one exception).
