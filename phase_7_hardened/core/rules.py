"""A project's own rules, and the profiles that choose what a review runs.

A rule is self-contained: one class that decides its own scope and its own verdict, and names its severity, its
title and its fix. Three kinds, one mental model — a line, a file, the tree. A `Rule` reads each line a change added
and answers yes or no, `tokens` reading that line as Python does. A `FileRule` reads each file the change touched,
whole at the head — its lines, which of them the change added and, for Python, its module — for what one line
cannot show. A `TreeRule` reads the head instead of the change: every path, and each Python module, parsed once
with the blast radius, for what must exist, define a name, derive from a parent or take a parameter. With no profile
named, a review runs the default: every rule there is, built in or the project's own, so a new rule runs until a
profile leaves it off. A profile only names which rules run, to narrow that, by id or by group. Rules live in the
phase's own `rules/` folder, profiles in its `config.toml`, and nowhere else: the repository under review configures
nothing, and no code of its runs. Pure, as the rest of the core is.
"""

from __future__ import annotations

import ast
import functools
import io
import tokenize
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import ClassVar

from .blast import parsed
from .findings import Finding, Severity
from .secrets import scrub

#: The source the project's own rules' findings carry in the report.
RULES = "gate_rules"
#: The profile a review runs when none is named: every built-in check and every rule in the folder.
DEFAULT = "default"


class AnyRule(ABC):
    """What every rule names, whatever it reads: its id, its severity, its title and its fix, each a sentence the
    report prints; and how it finds its hits. A rule's author writes only `check`."""

    id: ClassVar[str]
    severity: ClassVar[Severity]
    title: ClassVar[str]
    fix: ClassVar[str]
    #: What the rule reads, as `--list-rules` names it: a line, a file, the tree. Each kind below sets its own; a
    #: rule of its own shape, with its own `hits`, is custom.
    kind: ClassVar[str] = "custom"

    @abstractmethod
    def hits(self, files: list[dict], tree: Tree | None) -> list[tuple[str, int | None, str]]:
        """Each `(path, line, text)` the rule finds: on an added line, numbered from git's own hunk headers; in a
        changed file, at the line it names; or over the head, at a line where the rule knows one and else at the
        path. `UnreadError` where it could not look at what it asked for."""


class Rule(AnyRule):
    """One check over the lines a change added: it decides its own scope, and its own verdict on a line."""

    kind = "line"

    @abstractmethod
    def check(self, path: str, line: str) -> bool:
        """True when `line`, added to `path`, breaks the rule."""

    def hits(self, files: list[dict], tree: Tree | None) -> list[tuple[str, int | None, str]]:  # noqa: ARG002 -- a line rule reads no tree
        return [
            (entry["path"], line, f"+{text}")
            for entry in files
            for line, text in entry["added"]
            if self.check(entry["path"], text)
        ]


class ChangedFile:
    """One file a change touched, as a file rule reads it: its path, its text at the head as lines numbered from 1,
    the numbers of the lines the change added and, for a Python file, its module — the tree's parse where the head
    was listed, the file's own otherwise."""

    def __init__(self, path: str, text: str, added: Iterable[int], module: ast.Module | None = None) -> None:
        self.path = path
        self.lines = tuple(text.splitlines())
        self.added = frozenset(added)
        self._module = module

    def line(self, number: int) -> str:
        """Line `number`, counted from 1 as git and the report count; empty past the end."""
        return self.lines[number - 1] if 0 < number <= len(self.lines) else ""

    @functools.cached_property
    def module(self) -> ast.Module | str:
        """The file as Python reads it, or why there is no module: not a Python file, or it does not parse."""
        if self._module is not None:
            return self._module
        if not self.path.endswith(".py"):
            return "not read as Python"
        try:
            return ast.parse("\n".join(self.lines))
        except (SyntaxError, ValueError):
            return "does not parse"


class FileRule(AnyRule):
    """One check over each file a change touched, read whole at the head: its lines, which of them the change added
    and, for Python, its module — for what one added line cannot show: a sentence wrapped over several lines, a
    decorator and its definition, a function a change grew past a length."""

    kind = "file"

    @abstractmethod
    def check(self, file: ChangedFile) -> list[tuple[int | None, str]]:
        """Each `(line, what is wrong)` in `file`, the line numbered from 1 in the file at the head, None for the file
        as a whole; empty where it holds."""

    def hits(self, files: list[dict], tree: Tree | None) -> list[tuple[str, int | None, str]]:
        found: list[tuple[str, int | None, str]] = []
        for entry in files:
            text = entry.get("text")
            if text is None:
                if why := entry.get("unread_text"):  # the head holds it and it was not read: a hole, never silence
                    raise UnreadError(f"{entry['path']} {why}")
                continue  # deleted, binary, a link, a submodule: nothing at the head for a file rule to read
            module = tree.parsed.get(entry["path"]) if tree is not None else None
            file = ChangedFile(entry["path"], text, (line for line, _text in entry["added"]), module)
            found += [(entry["path"], line, what) for line, what in self.check(file)]
        return found


def findings_of(rules: Sequence[AnyRule], files: list[dict], tree: Tree | None) -> tuple[list[Finding], list[str]]:
    """Every rule over what it reads, a line rule over the lines a change added and a tree rule over the head, each
    finding named at its line or its path; and each rule that could not look, named: one that raised, a tree that
    was not listed, a file the head holds that was not read whole. A rule that could not look is never read as one
    that found nothing."""
    found: list[Finding] = []
    failed: list[str] = []
    for rule in rules:
        try:
            found += [
                Finding(
                    file=path,
                    line=line,
                    severity=rule.severity,
                    title=f"{rule.id}: {rule.title}",
                    evidence=scrub(text)[0],  # the report never prints a secret, a rule's evidence included
                    suggestion=rule.fix,
                )
                for path, line, text in rule.hits(files, tree)
            ]
        except UnreadError as exc:
            failed.append(f"rule {rule.id} could not look: {exc}")
        except (Exception, SystemExit) as exc:  # noqa: BLE001 -- the project's code: a failure, an exit too, is named
            failed.append(f"rule {rule.id} raised {type(exc).__name__}: {exc}")
    return found, failed


def chosen(
    profiles: dict, name: str, known: Sequence[str], groups: Mapping[str, Sequence[str]] | None = None
) -> tuple[str, list[str]]:
    """The check ids profile `name` turns on; `DEFAULT` is every one there is. A profile names a check by its id, or
    a group of them by the group's name — `rules`, every rule in the folder; `lanes`, every lane — spelled out
    here in the order the profile gives. Every profile is read first, and anything among them that does not mean
    exactly one thing — a profile that is no list of known ids, one that turns nothing on, one called `default`, an
    id two rules share, an id that is a group's name — is refused, never guessed at."""
    groups = dict(groups or {})
    if twice := sorted({rule for rule in known if known.count(rule) > 1}):
        raise ValueError(f"two rules share the id {twice[0]!r}; a built-in check's id is taken too")
    if taken := sorted(set(groups) & set(known)):
        raise ValueError(f"{taken[0]!r} is a group's name, and no check may take it")
    expanded: dict[str, list[str]] = {}
    for profile, ids in profiles.items():
        if profile == DEFAULT:
            raise ValueError(f"config.toml [profiles]: `{DEFAULT}` is every check, and no profile may take its name")
        expanded[profile] = expand(ids, known, groups, f"profile {profile!r}")
    if name == DEFAULT:
        return DEFAULT, list(known)
    if name not in profiles:
        raise ValueError(f"no profile {name!r}; there are {', '.join([DEFAULT, *sorted(profiles)])}")
    return name, expanded[name]


def expand(ids: object, known: Sequence[str], groups: Mapping[str, Sequence[str]], what: str) -> list[str]:
    """The check ids a list names — each an id among `known`, or a group's name standing for its ids — spelled out
    once each in the order given. `what` is the list as a sentence refusing it names it: a profile, or the `--check`
    flag; refused when it is no list, names something unknown, or turns nothing on."""
    if not isinstance(ids, list):
        raise ValueError(f"{what} must be a list of rule ids")
    if strangers := [check for check in ids if check not in known and check not in groups]:
        raise ValueError(
            f"{what} names {strangers[0]!r}, which no rule or group is; known: {', '.join(known)}"
            + (f"; groups: {', '.join(groups)}" if groups else "")
        )
    expanded = list(dict.fromkeys(check for named in ids for check in groups.get(named, [named])))
    if not expanded:
        raise ValueError(f"{what} turns no check on, and a review that looks at nothing approves anything")
    return expanded


def lines_hit(rule: Rule | FileRule, path: str, text: str) -> list[int]:
    """The lines of `text`, numbered from 1, that `rule` finds with all of it added to `path`: how a rule's author
    tries a rule on a file's worth of examples, and how `rules.self_check` reads a rule's own source."""
    numbered = list(enumerate(text.splitlines(), 1))
    if isinstance(rule, FileRule):
        file = ChangedFile(path, text, (number for number, _line in numbered))
        return sorted({line for line, _what in rule.check(file) if line is not None})
    return [number for number, line in numbered if rule.check(path, line)]


def tokens(line: str) -> list[tokenize.TokenInfo]:
    """The line as Python reads it, as far as it goes: a comment and a string are not code, an f-string's fields
    are, and a line is often a fragment, an open bracket or the middle of a docstring, whose tokens stop there."""
    found: list[tokenize.TokenInfo] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(line.strip() + "\n").readline):
            found.append(token)
    except (tokenize.TokenError, SyntaxError):
        pass
    return found


class UnreadError(LookupError):
    """Why a rule could not look: a file the head holds that was not read whole, as one past the size cap is, or a
    tree that was not listed. A hole, never a finding and never silence."""


class Tree:
    """The tree at the head, as a tree rule reads it: every path, each Python file read whole parsed once, for the
    blast radius and the rules alike, and the Python files not read whole."""

    def __init__(self, paths: Iterable[str], sources: Mapping[str, str], unread: Iterable[str] = ()) -> None:
        self.paths = frozenset(paths)
        self.unread = frozenset(unread)
        self.parsed = parsed(sources)

    def has(self, path: str) -> bool:
        """A file by its path, or a folder by its path ending in `/`."""
        if path.endswith("/"):
            return any(p.startswith(path) for p in self.paths)
        return path in self.paths

    def module(self, path: str) -> ast.Module | str:
        """`path` as Python reads it, or why there is no module: the head holds no such file, holds it as no Python
        file, or it does not parse. `UnreadError` where the head holds it and it was not read whole."""
        if path in self.unread:
            raise UnreadError(f"{path} was not read whole")
        if path not in self.paths:
            return "not at the head"
        if path not in self.parsed:
            return "not read as Python"
        return self.parsed[path] or "does not parse"

    def modules(self) -> Iterator[tuple[str, ast.Module]]:
        """Every Python module read at the head that parses, by path. A file not read whole is not here: the report's
        blast radius says how many, so a rule over the whole tree is read as a floor, never as silence."""
        for path in sorted(self.parsed):
            if (module := self.parsed[path]) is not None:
                yield path, module


def defined(module: ast.Module) -> set[str]:
    """The names a module defines at its top level: functions, classes, the names it assigns, one or several at a
    time, and the names it imports, which it exports as its own."""
    names: set[str] = set()
    for node in module.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names.update(name.id for name in getattr(target, "elts", [target]) if isinstance(name, ast.Name))
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
    return names


def classes(module: ast.Module) -> dict[str, list[str]]:
    """Each class a module defines at its top level, with its parents as written: `Exception`, `pydantic.BaseModel`."""
    return {
        node.name: [ast.unparse(base) for base in node.bases] for node in module.body if isinstance(node, ast.ClassDef)
    }


def parameters(module: ast.Module, function: str) -> list[str] | None:
    """The parameters of a top-level function by name: the positional ones, then the keyword-only ones, then `*args`
    and `**kwargs` by their names; None where the module defines no such function."""
    for node in module.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function:
            args = node.args
            names = [param.arg for param in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            names += [extra.arg for extra in (args.vararg, args.kwarg) if extra is not None]
            return names
    return None


class TreeRule(AnyRule):
    """One check over the tree at the head: what must exist, define a name, derive from a parent or take a
    parameter. Its expectations are its own constants, as a line rule's are."""

    kind = "tree"

    @abstractmethod
    def check(self, tree: Tree) -> list[tuple[str, str] | tuple[str, int | None, str]]:
        """Each `(path, what is wrong)` the head breaks — or `(path, line, what)` where the rule knows the line, as one
        over a module's syntax tree does; empty where it holds."""

    def hits(self, files: list[dict], tree: Tree | None) -> list[tuple[str, int | None, str]]:  # noqa: ARG002 -- a tree rule reads no lines
        if tree is None:
            raise UnreadError("the tree at the head was not listed")
        found: list[tuple[str, int | None, str]] = []
        for path, *rest in self.check(tree):
            line, what = rest if len(rest) == 2 else (None, rest[0])
            found.append((path, line, what))
        return found
