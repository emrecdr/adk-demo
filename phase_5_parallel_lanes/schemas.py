"""What a review is, as a type the code can read.

A finding that cannot point at the diff is worth nothing, so the schema makes
`evidence` a required field: the model cannot omit it. `output_schema` on
the reviewer agent turns this into the response schema the provider is asked
for, and ADK puts the parsed dict — not text — into session state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["blocker", "major", "minor"]


class Finding(BaseModel):
    file: str = Field(description="Repository-relative path of the file the finding is about.")
    line: int | None = Field(default=None, description="Line number in the new file, if it can be named.")
    severity: Severity = Field(description="blocker: must not merge; major: fix before merge; minor: worth fixing.")
    title: str = Field(description="One line naming the problem.")
    evidence: str = Field(description="The exact diff lines this finding is about, quoted verbatim.")
    suggestion: str = Field(description="What to change, concretely.")


class Review(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str = Field(description="One or two sentences on the change as a whole.")
