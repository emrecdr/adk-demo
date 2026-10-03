# Writing a rule

A rule is one Python class in one file in this folder. Drop the file in and the reviewer runs it: nothing to
register, nothing to configure. A rule names four things — an id, a severity, a title and a fix — and has one method,
`check`, which looks at the code and says what is wrong.

## In five minutes

1. Copy `_template.py` to a file named after your rule, `no_sleep.py` say. A file whose name starts with `_` is
   left aside, so the template never runs; your copy runs at once.
2. Fill in the four lines: `id = "no-sleep"`, `severity`, `title`, `fix`.
3. Write `check`.
4. See it listed, then run only it on a repository — no model, no key:

   ```bash
   uv run python -m phase_7_hardened.review --list-rules
   uv run python -m phase_7_hardened.review ~/repo --base main --check no-sleep
   ```

5. Test it (below), and add its id to `gates-only` in `config.toml` if that profile should run it; `default` runs
   it already.

## Three kinds, one mental model

Pick the smallest thing that answers the question: a line, a file, the tree.

**A line — `Rule`.** `check(path, line)` is called for every line the change added and answers yes or no. For
what one line tells: a call that should not be there, a word, a pattern. `tokens(line)` reads the line as Python
does, so a word in a comment or a string can be told from code.

```python
from ..core.rules import Rule


class NoSleep(Rule):
    """A sleep in library code hides a race; the fix is a wait on the thing itself."""

    id = "no-sleep"
    severity = "major"
    title = "time.sleep() in library code"
    fix = "Wait on the condition, or inject a clock the test can control."

    def check(self, path: str, line: str) -> bool:
        return path.endswith(".py") and "tests/" not in path and "time.sleep(" in line
```

**A file — `FileRule`.** `check(file)` is called once per changed file, with the whole file at the head:
`file.lines` (and `file.line(n)`, numbered from 1), `file.added` (the numbers of the lines the change added) and
`file.module` (the parsed Python, or a sentence saying why there is none). It returns `(line, what is wrong)`
pairs. For what needs more than one line: a function's length, a decorator and its definition, a sentence wrapped
over lines — `reviewer_instructions.py` is one.

```python
import ast

from ..core.rules import ChangedFile, FileRule

MAX_LINES = 40


class LongFunction(FileRule):
    """A function the change grew past a screen is a function nobody reads whole."""

    id = "long-function"
    severity = "minor"
    title = "a function longer than forty lines"
    fix = "Split it along the names its comments already use."

    def check(self, file: ChangedFile) -> list[tuple[int | None, str]]:
        module = file.module
        if not isinstance(module, ast.Module):
            return []  # not Python, or it does not parse: ruff names a syntax error
        return [
            (node.lineno, f"{node.name} is {node.end_lineno - node.lineno + 1} lines")
            for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.end_lineno - node.lineno + 1 > MAX_LINES
            and any(node.lineno <= n <= node.end_lineno for n in file.added)
        ]
```

**The tree — `TreeRule`.** `check(tree)` is called once with the whole head: `tree.has(path)` for a file, or a
folder as `"tests/"`; `tree.module(path)`; `tree.modules()` over every Python module, parsed once. It returns
`(path, what)` pairs, or `(path, line, what)` where you know the line. For the project's shape, which a diff cannot
show: what must exist, define a name, derive from a parent or take a parameter. `required_paths.py` is the whole of
one; `derives_from.py` reads every class.

## What a rule may do, and may not

- It reads what it is given and runs nothing: no process, no network, no environment, no file but the ones handed
  to it. `tests/test_layering.py` keeps it so.
- It never reads the repository under review's configuration: a branch must not be able to switch off the rule that
  judges it.
- Its expectations are constants at the top of its file, beside the check, so a reader finds them without opening
  another.
- Its id is kebab-case and unique; its severity is `blocker`, `major` or `minor`; the title names the problem in one
  line and the fix says what to do. The report prints all three.
- A rule that cannot look — a file not read whole, a tree not listed — is a hole in the review, never "nothing
  found". The base classes raise `UnreadError` for you; a rule of yours that raises anything is named in the report,
  and the run exits 3.

## Testing a rule

```python
from phase_7_hardened.core.rules import lines_hit
from phase_7_hardened.rules import self_check
from phase_7_hardened.rules.no_sleep import NoSleep


def test_no_sleep_finds_a_sleep_in_library_code_only() -> None:
    rule = NoSleep()
    assert lines_hit(rule, "src/pay.py", "import time\ntime.sleep(1)\n") == [2]
    assert lines_hit(rule, "tests/test_pay.py", "time.sleep(1)\n") == []
    assert self_check(rule) == []  # a rule that fires on its own source has read its words, not code
```

Tests live in `tests/`, beside the other rules' tests in `tests/test_hardened.py`; a test is named as the sentence
it proves.

## How a rule is run

- With no `--profile`, every rule in this folder runs. A profile in `config.toml` narrows that: a list of ids, with
  `rules` for all the rules and `lanes` for all the lanes. `--check ID` runs one check this once, repeatable.
- Findings appear under `gate_rules` in the report, at the line the rule named, with the id, the title and the fix.
  They are facts: the verifier never second-guesses them, and they count toward the verdict as a gate's do.
- A rule file that will not load, a rule missing one of its four parts, or an id used twice stops the run before it
  starts, exit 2, naming the file.

## When a rule is the wrong tool

ruff already checks hundreds of shapes, and `[lint]` in `config.toml` selects its families; a rule is for what no
tool checks: your project's own conventions. A question that needs judgement rather than a pattern is a lane
(`judge/lanes.py`, one row in `LANES`), not a rule.
