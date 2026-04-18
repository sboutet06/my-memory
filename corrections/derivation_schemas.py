"""Derivation-layer correction schemas.

Two kinds of derivation corrections:
  - EntityTypeBucket: batch review of entities sharing a doubtful type
    (typically the `concept` fallback bucket). Humans scan rows, set
    `override_type` where obvious, flip status=reviewed.
  - AliasCorrection: one file per ambiguous cluster. Human picks
    action = accept | merge | veto | split.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from corrections.schemas import CorrectionStatus, Doubt


class AliasAction(StrEnum):
    ACCEPT = "accept"   # accept pipeline's inferred decision
    MERGE = "merge"
    VETO = "veto"
    SPLIT = "split"


# ------------------------------ Entity types ------------------------------


class EntityTypeEntry(BaseModel):
    """One row in an entity-type bucket file."""

    name: str
    inferred_type: str
    override_type: Optional[str] = None
    evidence_docs: list[str] = Field(default_factory=list)

    def effective_type(self) -> str:
        return self.override_type or self.inferred_type


class EntityTypeBucket(BaseModel):
    """A batch file of entity-type doubts sharing a common reason."""

    bucket: str
    status: CorrectionStatus = CorrectionStatus.PENDING
    entries: list[EntityTypeEntry] = Field(default_factory=list)

    def overrides_by_name(self) -> dict[str, str]:
        """{name → override_type} for entries the human has set explicitly."""
        return {e.name: e.override_type for e in self.entries if e.override_type}


# --------------------------------- Aliases --------------------------------


_DEFAULT_ALIAS_OVERRIDES: dict[str, Any] = {
    "action": None,        # null (accept) | merge | veto | split
    "canonical": None,     # optional: which surface form wins
    "split_groups": [],    # list[list[str]]: partition members into sub-clusters
}


class AliasCorrection(BaseModel):
    """One ambiguous (or borderline) cluster flagged for human decision."""

    cluster: str   # slug, human-readable (used as filename stem)
    members: list[str]
    status: CorrectionStatus = CorrectionStatus.PENDING
    doubts: list[Doubt] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(
        default_factory=lambda: dict(_DEFAULT_ALIAS_OVERRIDES)
    )

    @field_validator("members")
    @classmethod
    def _non_empty_members(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("members must be non-empty")
        return v

    @field_validator("overrides")
    @classmethod
    def _validate_overrides(cls, v: dict[str, Any]) -> dict[str, Any]:
        out = dict(_DEFAULT_ALIAS_OVERRIDES)
        out.update(v or {})
        action = out.get("action")
        if action is not None and action not in {a.value for a in AliasAction}:
            raise ValueError(
                f"action must be null or one of {[a.value for a in AliasAction]}"
            )
        return out

    def effective_action(self) -> AliasAction:
        action = self.overrides.get("action")
        return AliasAction(action) if action else AliasAction.ACCEPT
