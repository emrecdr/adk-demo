"""A second deterministic gate: ruff over the changed Python files at the head commit.

Two gates make the point one gate only hints at: tools produce findings
deterministically, before any model runs, and adding a gate is a function.
Ruff runs with `--isolated` and the rules `config.toml` selects and ignores, never the
reviewed repository's own configuration: a change must not be able to configure the
gate that judges it, nor, with `--ignore-noqa`, silence it line by line. The
files are written from the head commit into a temporary directory; nothing
runs from, or writes into, the repository under review. Without ruff on
`PATH`, or with one that fails, the gate did not look, and says so: its
answer is the reason, the run is degraded and the report names it, for the
reason a failed lane is named rather than empty — "did not look" must never
read as "found nothing". `uv run` puts the project's own ruff on `PATH`, so
the demo never sees that. Every hit on a changed file is reported, on an
added line or not: ruff reads whole files, and a reviewer told the file and
line can tell the two apart; the secrets gate reads only added lines because
it reads the diff.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath, PurePosixPath

from ..core.findings import Finding
from ..core.secrets import scrub
from .git import GitError, files_at_head, on_path

#: The gate's name in the report.
LINT = "gate_lint"
#: A ruff code's severity: the longest key the code begins with inside its own family, keyed by ruff's own prefixes
#: and codes, so `S` never reaches `SIM108` and `C90` reaches `C901` but not `C416`; anything else is minor. An
#: unused import or local is hygiene, not a defect. A file that does not parse is major: ruff reads no other rule
#: in it, so a `shell=True` inside one went unreported and its one finding read as a nit.
SEVERITY = {
    "F": "major",
    "F401": "minor",
    "F841": "minor",
    "B": "major",
    "S": "major",
    "ASYNC": "major",
    "C90": "major",
    "RUF006": "major",
    "T10": "major",
    "invalid-syntax": "major",
}
#: The fix a finding names when ruff offers none: ruff says what is wrong, not what to do. Keyed as `SEVERITY` is:
#: by family, since a sentence true of every rule in one is worth more than a guess per code, and by code where the
#: family's would mislead.
FIX = {
    "invalid-syntax": "Fix the syntax: ruff reads no other rule in a file that does not parse.",
    "E501": "Wrap the line.",
    "E": "Correct what pycodestyle reports.",
    "W": "Resolve the style warning.",
    "F401": "Remove the unused import, or export it on purpose.",
    "F841": "Remove the unused variable, or use its value.",
    "F": "Correct what pyflakes reports; an undefined or redefined name is a bug.",
    "B": "Rewrite the pattern: bugbear names shapes known to misbehave.",
    "S": "Use the safe form of the call; the security lane weighs what is left.",
    "C90": "Split the function until each part reads on its own.",
    "PLR": "Bring the count under ruff's threshold by extracting part of the construct.",
    "ASYNC": "Move the blocking call off the event loop, or await its async equivalent.",
    "RUF006": "Keep a reference to the task and await it, so its failure is seen.",
    "T10": "Remove the debugger call.",
    "ERA": "Delete the commented-out code: version control keeps it.",
}


def family(code: str) -> str:
    """`PLR0913` -> `PLR`, `E501` -> `E`: the letters ruff prints before the number. One letter can be two linters'
    (mccabe's `C90`, flake8-comprehensions' `C4`), which `tier`'s longest key tells apart."""
    return code.rstrip("0123456789")


def tier(table: Mapping[str, str], code: str) -> str | None:
    """The table's entry for `code`: the longest key it begins with inside its own family, so `S` never reaches
    `SIM108`, `C90` reaches `C901` and not `C416`, and `E501` wins over `E`; None where the table has none."""
    keys = [key for key in table if code.startswith(key) and family(key) == family(code)]
    return table[max(keys, key=len)] if keys else None


def severity_of(code: str) -> str:
    """The code's tier, else minor."""
    return tier(SEVERITY, code) or "minor"


def fix_for(code: str, offered: str | None) -> str:
    """Ruff's own fix when it offers one, else the code's or its family's sentence, else a pointer."""
    return offered or tier(FIX, code) or f"see ruff rule {code}"


RUFF_TIMEOUT_S = 60


def lint_findings(evidence: dict, select: Sequence[str], ignore: Sequence[str] = ()) -> list[Finding] | str:
    """Ruff's findings on the Python files the change touched, at the head commit — or, as a string, why it did
    not look. `select` and `ignore` are `config.toml`'s `[lint]`: the gate reads no other configuration."""
    ruff = on_path("ruff")  # by its full path: on Windows the current directory is searched first
    if ruff == "ruff":  # the name alone: found nowhere on PATH
        return "ruff is not on PATH, so the gate did not look; `uv run` puts the project's own there"
    paths = [f["path"] for f in evidence["files"] if f["path"].endswith(".py") and f["status"] != "D"]
    if not paths:
        return []
    try:
        return _lint(ruff, paths, evidence["preflight"], select, ignore)
    except GitError as exc:
        return f"{exc}, so the gate did not look"
    except OSError as exc:  # a disk that refuses the write: full, or read-only
        return f"a changed file could not be written to lint ({exc.strerror}), so the gate did not look"
    except (ValueError, KeyError, TypeError) as exc:  # an answer of another shape than ruff's JSON
        return f"ruff's answer could not be read ({type(exc).__name__}), so the gate did not look"
    except subprocess.CalledProcessError as exc:  # ruff's cause sits on no fixed line, so all it said goes, flat
        said = " ".join(exc.stderr.split()) or "no reason given"
        return f"ruff exited {exc.returncode}: {said}, so the gate did not look"
    except subprocess.TimeoutExpired:
        return f"ruff did not answer within {RUFF_TIMEOUT_S} s, so the gate did not look"


def _lint(ruff: str, paths: list[str], resolved: dict, select: Sequence[str], ignore: Sequence[str]) -> list[Finding]:
    """Ruff over `paths` as they stand at the head, written into a temporary directory: its findings, or it raises
    — git failing to read a file, ruff failing, or git or ruff past its timeout — for `lint_findings` to name.
    Under `--exit-zero` a finding never fails ruff, so any other exit is a ruff that could not run."""
    with tempfile.TemporaryDirectory() as tmp:
        sources: dict[str, list[str]] = {}
        targets = []
        texts = files_at_head(resolved, paths)
        for index, (path, text) in enumerate(zip(paths, texts, strict=True)):
            # Each in a folder of its own, under a name of the gate's own, never the branch's: `x.py` beside
            # `X.py/y.py` collided on a case-insensitive disk, `../../x.py` was written outside the folder, and
            # Windows holds no `nul.py`, `a:b.py` or control character. Ruff, `--isolated`, reads only the name
            # `__init__.py` from a file's path, so that one is kept.
            name = "__init__.py" if PurePosixPath(path).name == "__init__.py" else "module.py"
            target = f"{index}/{name}"
            written = Path(tmp, target)
            written.parent.mkdir()
            written.write_text(text, encoding="utf-8", newline="")
            targets.append(target)
            # Split where ruff counts a row: `str.splitlines` breaks at a form feed or U+2028 too, and measured, the
            # quote after one was the line above ruff's.
            sources[path] = re.split(r"\r\n?|\n", text)
        # Every file by name, never a folder: ruff's default excludes skipped a `.venv/` or `node_modules/` a branch
        # had changed, never a file it is named. `--ignore-noqa`: an inline noqa comment in the branch silenced it.
        # `--no-cache`: nothing is written beside the files, which Windows could hold open when the folder goes.
        argv = [ruff, "check", "--no-fix", "--no-cache", "--isolated", "--exit-zero", "--ignore-noqa"]
        argv += ["--select", ",".join(select), *(["--ignore", ",".join(ignore)] if ignore else [])]
        argv += ["--output-format", "json", *targets]
        done = subprocess.run(
            argv, cwd=tmp, capture_output=True, encoding="utf-8", errors="replace", timeout=RUFF_TIMEOUT_S, check=True
        )
        hits = json.loads(done.stdout)
        findings = []
        for hit in hits:
            path = paths[int(PurePath(hit["filename"]).parts[-2])]  # `<index>/<name>`, however ruff spells the root
            row = hit["location"]["row"]
            code = hit["code"] or "invalid-syntax"  # ruff 0.12.0 to 0.12.7 name a file that does not parse with null
            lines = sources.get(path, [])
            line = lines[row - 1] if 0 < row <= len(lines) else ""
            fix = (hit.get("fix") or {}).get("message")
            findings.append(
                Finding(
                    file=path,
                    line=row,
                    severity=severity_of(code),
                    title=f"{code} {hit['message']}",
                    evidence=scrub(line)[0],  # a lint hit may quote the very line the secrets gate found
                    suggestion=fix_for(code, fix),
                )
            )
    return findings
