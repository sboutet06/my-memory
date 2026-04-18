"""Pydantic schemas for correction files."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class CorrectionStatus(StrEnum):
    PENDING = "pending"
    REVIEWED = "reviewed"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SuggestedAction(StrEnum):
    CONFIRM = "confirm"
    PROVIDE = "provide"
    REPLACE = "replace"
    REVIEW = "review"


class Doubt(BaseModel):
    """One uncertainty the pipeline emits for human review."""

    field: str
    inferred_value: Any = None
    confidence: Confidence
    rationale: str
    suggested_action: SuggestedAction

    @field_validator("rationale")
    @classmethod
    def _rationale_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("rationale must be non-empty")
        return v


_DEFAULT_OVERRIDES: dict[str, Any] = {
    "metadata": {},
    "content_replacements": [],
    "tags": [],
}


class SourceCorrection(BaseModel):
    """Overlay file for a single ingested document."""

    document_id: str
    original_filename: str
    status: CorrectionStatus = CorrectionStatus.PENDING
    doubts: list[Doubt] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=lambda: dict(_DEFAULT_OVERRIDES))
    replaced_by: Optional[str] = None

    @field_validator("overrides")
    @classmethod
    def _ensure_override_shape(cls, v: dict[str, Any]) -> dict[str, Any]:
        out = dict(_DEFAULT_OVERRIDES)
        out.update(v or {})
        return out
