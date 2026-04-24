"""Derivation-layer correction schemas.

Three kinds of derivation corrections:
  - EntityTypeBucket: batch review of entities sharing a doubtful type
    (typically the `concept` fallback bucket). Humans scan rows, set
    `override_type` where obvious, flip status=reviewed.
  - AliasCorrection: one file per ambiguous cluster. Human picks
    action = accept | merge | veto | split.
  - ConflictCorrection: one file per detected conflict. Human picks
    a resolution: winner, coexist, or temporal_supersede order.
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


# ----------------------------- Conflicts ----------------------------------


class ConflictResolution(BaseModel):
    """Human decision for resolving a Conflict.

    Exactly one resolution mode should be set:
      winner: <fact_id>                   — one fact is correct
      coexist: true                       — multiple values are simultaneously valid
      temporal_supersede_order: [old, new] — ordered earliest → latest
    """

    winner: Optional[str] = None
    coexist: bool = False
    temporal_supersede_order: list[str] = Field(default_factory=list)


class ConflictFactEntry(BaseModel):
    """One competing fact in a ConflictCorrection file."""

    fact_id: str
    value: str = ""
    source_doc: str = ""


class ConflictCorrection(BaseModel):
    """One YAML file per detected Conflict. Human edits the resolution section."""

    conflict_id: str
    subject_id: str
    predicate: str
    status: str = "open"  # open | reviewed
    competing_facts: list[ConflictFactEntry] = Field(default_factory=list)
    resolution: Optional[ConflictResolution] = None
