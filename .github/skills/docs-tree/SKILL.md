---
name: docs-tree
description: Bring the file tree in docs/ITERATION_MAP.md section 3 and the phase READMEs' file claims back in step with the working tree after files were added, removed, renamed or moved, so tests/test_docs.py passes. Use after any change to the set of files in the repository.
---

# Keep the map's tree and the README claims true

`tests/test_docs.py` fails when the §3 tree in `docs/ITERATION_MAP.md` and the working tree differ in either
direction, or when a phase README's claim about a `*.py` file is false. The tree's grammar and the claims' are stated
in `.github/instructions/docs.instructions.md`, which loads with any Markdown file.

1. See the difference: `uv run pytest -q tests/test_docs.py` names what is in the working tree but not in the tree,
   and the reverse.
2. Edit the tree block under `## 3. Shape of the repository`, one entry a line, in the grammar the instructions
   state; a comment after the name says what the file is for.
3. For a `*.py` added, removed or changed directly in a phase folder, fix that phase README's claim sentence, and
   the next phase's, since its `Unchanged:` compares bytes with this one.
4. Run `uv run pytest -q tests/test_docs.py` again; leave no date and no count behind.
