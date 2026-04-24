"""Fact/Claim/Conflict/Predicate Pydantic schemas — Phase 6.

All IDs are content-addressable (SHA-256) so the same semantic fact
always produces the same ID regardless of insertion order or host.
Computed fields are serialized in model_dump() / model_dump_json() but
are ignored on deserialization — they're always recomputed from the
stored fields, guaranteeing consistency.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field


def _sha256(*parts: str) -> str:
    """SHA-256 of pipe-joined string parts — stable content-addressable ID."""
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()


class Fact(BaseModel):
    """A single asserted fact: subject has predicate = canonical_value.

    id = SHA-256(subject_id | predicate | canonical_value | source_doc_id)

    Including source_doc_id in the ID means two documents asserting the
    same (subject, predicate, canonical_value) produce distinct Facts, each
    backed by its own Claim. The Conflict detector collapses same-value
    duplicates and surfaces different-value conflicts.
    """

    subject_id: str
    predicate: str
    canonical_value: str
    value: Union[str, dict[str, Any]] = ""
    source_doc_id: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return _sha256(self.subject_id, self.predicate, self.canonical_value, self.source_doc_id)


class Claim(BaseModel):
    """Evidence for a Fact: which document, where, by which extractor.

    id = SHA-256(fact_id | source_doc_id | source_location | extractor)
    """

    fact_id: str
    source_doc_id: str
    source_location: str = ""
    extractor: str
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    ingestion_version: int = Field(default=1, ge=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return _sha256(self.fact_id, self.source_doc_id, self.source_location, self.extractor)


class Conflict(BaseModel):
    """Two or more Facts with the same (subject_id, predicate) but different values.

    id = SHA-256(subject_id | predicate) — stable as competing_fact_ids grows.
    Status transitions: open → resolved_manually | resolved_temporally.
    """

    subject_id: str
    predicate: str
    competing_fact_ids: list[str] = Field(default_factory=list)
    status: Literal["open", "resolved_manually", "resolved_temporally"] = "open"
    resolution: Optional[dict[str, Any]] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return _sha256(self.subject_id, self.predicate)


class Predicate(BaseModel):
    """Registry entry for a semantic predicate (Phase 7 consumption).

    Packs declare predicates via Pack.predicates; core merges them into a
    registry. Unknown predicates default to time_varying=False,
    allow_multi=False — which means two different values → Conflict (D2).
    """

    name: str
    time_varying: bool = False
    allow_multi: bool = False
    description: str = ""
