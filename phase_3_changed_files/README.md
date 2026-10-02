# Phase 3 — changed files

Phase 2 plus two tools and a guardrail. The agent lists what the branch
changed and shows a capped diff of any one changed file. It is the first
phase where a tool argument is treated as hostile input: the model chooses
the arguments, and a review agent that can be talked into
`show_diff("/etc/passwd")` is a file reader with a chat interface.

## What changed since phase 2

- **New: `callbacks.py`.** `only_changed_paths(tool, args, tool_context)` is
  a `before_tool_callback`. It refuses a `repo` that is not a directory, and
  for `show_diff` it refuses a path until `changed_files` has
  run, an absolute path, a path containing `..`, and any path the change did
  not touch. Returning a dict answers the model without running the tool;
  returning `None` lets the call through.
- **Changed: `tools.py`.** `inspect_repository` gains a `tool_context` and
  leaves the scope it confirmed in `tool_context.state["review_scope"]`; the
  tools after it read that and take no repository at all. `changed_files(tool_context)`
  runs `git diff-tree -r --name-status -z -M` from the merge base, handles renames and
  copies (a rename carries its old path), and writes the allowlist the callback reads into
  `tool_context.state["review_files"]`, each path with the old one a rename carries.
  `show_diff(path, tool_context)` returns one file's unified diff, a rename read
  with its old path so it shows the lines it moved and changed, as git prints it for no one's settings — through
  plumbing, `diff-tree -r -p`, which reads none of the repository's display settings, the path taken literally, the merge base's attributes rather than the branch's, no
  colour, external diff or text conversion — cut at `DIFF_CAP_CHARS` (4,000) with the cut named
  in the text and a `cut` flag. A parameter named `tool_context` is filled in
  by ADK, never by the model. Measured in chat mode before the scope lived in
  state: every tool resolved the repository again, twenty-nine git processes
  where nine would do.
- **Changed: `agent.py`.** Three tools, `before_tool_callback=[only_changed_paths]`,
  and an instruction that lists files first and shows a diff only when asked.
- Unchanged: `__init__.py`, `config.py`.

## Run it

```bash
uv run adk run phase_3_changed_files
```

Three messages, in order:

```
review <demo repo>, branch feature/payments against main
show me the diff of src/payments/charge.py
show me the diff of /etc/passwd
```

`<demo repo>` is the path `scripts/make_demo_repo.py` printed. Expect the preflight lines and four files (`M src/payments/charge.py`,
`A src/payments/config.py`, `A src/payments/refund.py`, `A src/payments/report.py`);
then the diff in a fenced block; then a refusal. Among the event cards the
third message shows the model's `show_diff` call answered by the callback's
error dict; the tool itself never ran. That refusal is the point of the phase.

## What to notice

- Tool arguments are untrusted input. The guardrail sits in front of the
  tool, not inside it, so the tool stays simple and the policy is in one place.
- `ToolContext.state` is how one tool's answer becomes the next tool's
  boundary: `inspect_repository` writes the scope, `changed_files` reads it
  and writes the allowlist, `show_diff` is held to both.
- Everything a model reads is capped in characters, and the cut is named. A
  truncation the model cannot see is a bug it will report on.
