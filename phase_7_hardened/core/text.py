"""The two string rules every group shares: whitespace flattened, and a cut that names itself.

Pure, and here rather than beside their first callers because both sides of
the model boundary use them: `collect` cuts a diff before a model reads it,
`deliver` cuts a quote before a person does, and grounding and the report
flatten whitespace the same way, so what counts as grounded cannot move when
the report's rule does.
"""

from __future__ import annotations

#: A reason is read by a person: a verifier's prose, a raw exception that escaped the engine; 400 characters say it.
REASON_MAX_CHARS = 400


def squash(text: str) -> str:
    """`text` with every run of whitespace, newlines included, as one space."""
    return " ".join(text.split())


def cut_at(text: str, limit: int, *, sep: str = " ") -> str:
    """`text` cut at `limit` characters with the cut named, as every cap in this demo names its cut.

    `sep` sits between the kept text and the marker: a space inline, a newline after a block.
    """
    return text if len(text) <= limit else f"{text[:limit]}{sep}[… cut at {limit:,} characters]"
