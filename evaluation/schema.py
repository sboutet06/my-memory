"""Pydantic models for eval cases and per-case results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

QueryMode = Literal["hybrid", "local", "global", "naive", "mix"]


class EvalCase(BaseModel):
    """A single gold-standard question with expectations.

    Every expectation is optional — an empty list scores as "perfect" on
    that dimension. This lets cases grow incrementally (write the
    question first, add expectations as dogfooding surfaces them).
    """

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    mode: QueryMode = "hybrid"
    expected_documents: list[str] = Field(default_factory=list)
    expected_entities: list[str] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    expected_provenance: list[str] = Field(default_factory=list)
    expected_conflicts: list[str] = Field(default_factory=list)
    forbidden_facts: list[str] = Field(default_factory=list)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class EvalCaseResult(BaseModel):
    """One scored execution of one case."""

    case_id: str
    question: str
    mode: QueryMode
    answer: str
    document_ids: list[str]
    doc_coverage: float
    entity_coverage: float
    fact_coverage: float
    fact_provenance_coverage: float = 1.0
    conflict_detection_coverage: float = 1.0
    forbidden_violations: int
    passed: bool  # True iff all coverages==1 and forbidden_violations==0


def load_cases(path: Path) -> list[EvalCase]:
    """Load a `cases.json` file shaped like `{"cases": [EvalCase, …]}`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = data.get("cases", [])
    return [EvalCase.model_validate(c) for c in raw_cases]
