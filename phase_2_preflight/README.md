# Phase 2 — preflight

Phase 1 plus one tool. The agent asks for a repository path and the branch
under review (the base is `main` unless named), proves both branches exist with a single read-only git tool, and
prints a preflight block before anything else happens: repository, branch and sha, base and sha, merge-base, commits ahead.

## What changed since phase 1

- **New: `tools.py`.** `_git(repo, *args)` runs `git -C <repo> …`, git by its
  full path from `PATH` and never from the current directory, as an argv
  list with a 30-second timeout that stops the whole command, no shell, in `_environment(repo)`: no
  inherited `GIT_*` variable (`GIT_DIR`, `GIT_DIFF_OPTS` and the rest), no
  global or system config and no attributes file but the repository's, so no
  one's own settings change what git prints, the one repository named as
  its safe directory, no lazy fetch (a partial clone would fetch what it lacks
  into the repository), no replace refs or grafts, and two settings that
  change what git prints fixed; stdout read as bytes and
  decoded as UTF-8 by hand, so a lone `\r` inside a line stays in it; a call
  that fails raises `GitError` with git's own first line, and so do one that
  cannot start (no git on `PATH`) and one past the timeout, naming the limit; the tool answers either as an error envelope.
  Two exit codes of 1 are answers, not failures: a ref that does not exist,
  and two branches with no history in common.
  `_sha(repo, ref)` is `rev-parse --verify --quiet --end-of-options <ref>^{commit}`,
  the commit even when the name is an annotated tag. `_namesakes(repo, ref)`
  lists every full ref a name could mean, however it is spelled after
  (`main~0` is still `main`), and the objects a hex name abbreviates when a
  ref has that name too; a name that means two things is refused rather
  than resolved, and the full ref
  each name resolved through comes back as `base_ref` and `head_ref`.
  `inspect_repository(repo, base, head)` is the tool: it checks for a `.git`
  directory, refuses a shallow clone, whose merge base can be the wrong one,
  resolves both refs, and returns the merge base and the commit count, or an
  error envelope.
- **Changed: `agent.py`.** Gains `tools=[inspect_repository]`, an instruction
  that says what to ask for, when to call the tool and the exact five lines
  to answer with, and `output_key="preflight"`, which writes the reply into
  session state.
- Unchanged: `__init__.py`, `config.py`.

## Run it

```bash
uv run python scripts/make_demo_repo.py   # once: main + feature/payments in the platform's temp directory
uv run adk run phase_2_preflight
```

```
review <demo repo>, branch feature/payments against main
```

`<demo repo>` is the path the script printed: `adk-demo-repo` in the
platform's temp directory. Expect the five lines with nine-character hashes. Then ask for
`branch feature/nope against main`: the answer is one polite sentence
repeating the tool's error message, not a stack trace.

## What to notice

- ADK builds the tool's schema from the function signature and its
  docstring, so the docstring is prompt material: it tells the model when to
  call the tool and what comes back.
- A tool returns `{"status": "success", …}` or `{"status": "error", "error_message": …}`
  and never raises at the model. An exception would end the turn; an envelope
  lets the model explain.
- Git is an argv list, never a shell, and only verbs that read. Where a user
  string reaches git as a bare argument it carries `--end-of-options`, so a
  ref spelled `-x` is a ref, never a flag; elsewhere it sits behind `refs/`
  or inside an option's value, and after the preflight git only sees hashes.
- `output_key` is how an agent's answer lands in session state. Phase 3 reads
  state from inside a tool.
