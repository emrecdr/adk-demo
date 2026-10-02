"""The report a person reads in a terminal, and every rule that keeps model prose from forging it."""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..core.blast import Blast, describe
from ..core.findings import Finding
from ..core.secrets import scrub
from ..core.text import REASON_MAX_CHARS, cut_at, squash
from ..core.verdict import Outcome, Sourced, ungrounded_at

#: A quote is read by a person, who has its file and line for the rest. A gate quotes the whole added line, and a
#: minified one ran to 200,000 characters. Cut after the scrub, so no cut halves a credential past its pattern.
EVIDENCE_MAX_CHARS = 400
#: What a terminal runs or reorders: escape sequences, C0 and C1 controls (U+009B is `ESC [` in one character), and
#: the marks that turn the text after them around (U+202E and its kin).
_CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def one_line(text: str) -> str:
    """Model prose as one markdown line: escape sequences and control characters out, whitespace flat.

    The report is read in a terminal and pasted into chats. Measured: a title
    holding a newline forged a second `## Verdict` heading, a newline in a
    suggestion forged a bullet, and `ESC[2J` cleared the terminal. A credential
    in it is hidden too: the report never prints one. Presentation
    only: grounding (`core.verdict.as_seen`) squashes whitespace and nothing
    else, so what counts as grounded cannot move when the report's safety rule
    does.
    """
    return squash(_CONTROL.sub(" ", scrub(text)[0]))


#: A CI runner's command in its log: Azure runs `##vso[` and GitHub `##[` anywhere in a line, GitHub across invisible
#: characters between them (measured on .NET), so any non-ASCII run counts. GitHub's `::` counts only opening a line,
#: and no printed line opens with the branch's text.
_RUNNER_COMMAND = re.compile(r"#[^ -~]*#[^ -~]*(?:vso)?(?=\[)")


def inert(text: str) -> str:
    """`text` with each CI runner's command opener broken by a space, `##vso [`, and each HTML comment's, `<! --`,
    which hid what lay between two paths wherever the report renders as markdown: paths and quotes are the branch's."""
    return _RUNNER_COMMAND.sub(r"\g<0> ", text).replace("<!--", "<! --")


def code_span(text: str) -> str:
    """`text` as a markdown code span fenced to beat its own backticks: a lane quotes source, and source has them."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def _reason(text: str) -> str:
    """A model's or a provider's words about a finding or a lane, as one line of readable length."""
    return cut_at(one_line(text), REASON_MAX_CHARS)


def _named(items: list[tuple[Sourced, str]]) -> list[str]:
    """One line per finding and what became of it: neither a removal nor a failure is silent."""
    return [f"  - `{item.source}`: {one_line(item.finding.title)} — {_reason(reason)}" for item, reason in items]


def _blast(blast: Blast) -> list[str]:
    """Where a person reads closely and where a skim will do: what depends on each changed file, widest first.

    Before the verdict, because it says how to read everything under it. A path is the reviewed branch's
    text, so it is flattened and fenced like a lane's prose.
    """
    lines = ["## Blast radius", ""]
    lines += [f"- {code_span(one_line(r.path))}: {one_line(describe(r, blast.floor))}" for r in blast.radii]
    if not blast.listed:
        lines.append("- not read: the head's tree could not be listed; every count above is a floor")
    elif blast.floor:
        lines.append(
            f"- not read: {len(blast.unparsed)} file(s) the parser refused, {blast.skipped} over a cap, past a timeout"
            " or not in the clone; every count above is a floor, and so is any rule over the tree"
        )
    return [*lines, ""]


def _as_resolved(name: str, ref: str) -> str:
    """A name as given, and the tag it resolved through when it is one: a fork's tag `origin/main`, with no such
    branch fetched, once stood in for the branch unseen."""
    return f"{name} (the tag {ref})" if ref.startswith("refs/tags/") else name


def _where(f: Finding) -> str:
    """A finding's file and line as one line: the path is the branch's text."""
    return one_line(f"{f.file}:{f.line}" if f.line else f.file)


def render(
    evidence: dict,
    outcome: Outcome,
    *,
    verdict: str,
    spend: str,
    fail_on: str,
    model: str,
    profile: str,
    off: Sequence[str],
    sources: Sequence[str],
) -> str:
    """`evidence` is `collect_evidence`'s; `profile` is the profile that ran and `off` what it left off, named so a
    reader sees what was never asked; `sources` are the checks that ran, in report order, each a section whether it
    found anything or not."""
    pre, files, scope = evidence["preflight"], evidence["files"], evidence["scope"]
    if evidence["whole"]:  # no base: every file at the head, each read as added
        title, against = f"# Review: every file at {pre['head']}", ["- against      nothing: every file, as if added"]
        listed, kind = "files", "file(s)"
    else:
        title = f"# Review: {pre['head']} against {pre['base']}"
        against = [
            f"- against      {_as_resolved(pre['base'], pre.get('base_ref', ''))} @ {pre['base_sha'][:9]}",
            f"- merge-base   {pre['merge_base'][:9]}",
        ]
        listed, kind = "changed", "changed file(s)"
    left = f"{evidence['outside']} {kind} outside it, not reviewed"
    lines = [
        title,
        "",
        f"- repository   {pre['repo']}",
        f"- branch       {_as_resolved(pre['head'], pre.get('head_ref', ''))} @ {pre['head_sha'][:9]}",
        *against,
        *([f"- model        {model}"] if model else []),
        f"- profile      {profile}" + (f" (off: {', '.join(off)})" if off else ""),
        *([f"- scope        {one_line(', '.join(scope))}: {left}"] if scope else []),
        f"- {listed:<12} {len(files)} file(s): " + ", ".join(code_span(one_line(f["path"])) for f in files),
        *(f"- not read     {code_span(one_line(path))}: {why}" for path, why in outcome.unread.items()),
        "",
        *_blast(evidence["blast"]),
        f"## Verdict: {verdict}",
        "",
    ]
    for source in sources:
        findings = [item.finding for item in outcome.kept if item.source == source]
        failed = outcome.errors.get(source)
        lines.append(f"### {source}" + (f" — FAILED: {_reason(failed)}" if failed else ""))
        for f in findings:
            lines += [
                f"- **{f.severity}** {one_line(f.title)} ({_where(f)})",
                f"  - evidence: {code_span(cut_at(one_line(f.evidence), EVIDENCE_MAX_CHARS))}",
                f"  - fix: {one_line(f.suggestion)}",
            ]
        # Named under its own source: measured live, ruff's every hit folded into a lane's blocker on the same lines,
        # and its section read "no findings" under a gate that had found `shell=True`.
        folded = [(item.finding, into.source) for item, into in outcome.folded if item.source == source]
        for f, into in folded:
            lines.append(f"- folded into `{into}`'s finding on the same lines: {one_line(f.title)} ({_where(f)})")
        if not findings and not folded and not failed:
            lines.append("- no findings")
        lines.append("")
    lines.append(f"- findings dropped for evidence not in the diff: {len(outcome.dropped)}")
    if severe := ungrounded_at(outcome, fail_on):
        lines.append(f"  - {severe} at or above `--fail-on {fail_on}`: not approved until a person reads them")
    # Named with the quote, so a reader can tell a lane that invented one from one that merely paraphrased.
    quoted = [(item, f"quoted {code_span(cut_at(one_line(item.finding.evidence), 120))}") for item in outcome.dropped]
    lines += _named(quoted)
    if outcome.verified:
        lines += [
            f"- findings refuted by the verifier: {len(outcome.refuted)}",
            *_named(outcome.refuted),
            f"- findings the verifier could not judge, kept: {len(outcome.unverified)}",
            *_named(outcome.unverified),
        ]
    lines += [
        f"- duplicates across gates and lanes folded into one finding: {len(outcome.folded)}",
        f"- secrets redacted before any model call: {outcome.redacted}",
        spend,
        "",
    ]
    return inert("\n".join(lines))  # once over the whole: no two fields side by side spell one
