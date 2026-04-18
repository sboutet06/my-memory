"""Derivation-layer schemas: entity-type buckets + alias clusters."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from corrections.derivation_schemas import (
    AliasAction,
    AliasCorrection,
    EntityTypeBucket,
    EntityTypeEntry,
)
from corrections.schemas import (
    Confidence,
    CorrectionStatus,
    Doubt,
    SuggestedAction,
)


def _doubt() -> Doubt:
    return Doubt(
        field="merge_decision", inferred_value="merge",
        confidence=Confidence.MEDIUM, rationale="r",
        suggested_action=SuggestedAction.CONFIRM,
    )


class TestEntityTypeEntry:
    def test_minimal(self) -> None:
        e = EntityTypeEntry(name="Gabriel", inferred_type="concept")
        assert e.override_type is None
        assert e.evidence_docs == []

    def test_with_override(self) -> None:
        e = EntityTypeEntry(
            name="Gabriel", inferred_type="concept",
            override_type="person", evidence_docs=["lettre_mv4"],
        )
        assert e.override_type == "person"

    def test_effective_type_prefers_override(self) -> None:
        e = EntityTypeEntry(name="X", inferred_type="concept", override_type="person")
        assert e.effective_type() == "person"

    def test_effective_type_falls_back_to_inferred(self) -> None:
        e = EntityTypeEntry(name="X", inferred_type="concept")
        assert e.effective_type() == "concept"


class TestEntityTypeBucket:
    def test_empty_bucket(self) -> None:
        b = EntityTypeBucket(bucket="concept_fallback")
        assert b.status == CorrectionStatus.PENDING
        assert b.entries == []

    def test_name_lookup(self) -> None:
        b = EntityTypeBucket(
            bucket="concept_fallback",
            entries=[
                EntityTypeEntry(name="Gabriel", inferred_type="concept"),
                EntityTypeEntry(name="Cagnes", inferred_type="concept", override_type="location"),
            ],
        )
        assert b.overrides_by_name() == {"Cagnes": "location"}


class TestAliasCorrection:
    def test_members_required(self) -> None:
        with pytest.raises(ValidationError):
            AliasCorrection(cluster="x", members=[], doubts=[_doubt()])

    def test_inferred_default(self) -> None:
        a = AliasCorrection(
            cluster="sebastien_boutet",
            members=["Sébastien Boutet", "SEBASTIEN BOUTET"],
            doubts=[_doubt()],
        )
        assert a.overrides["action"] is None
        assert a.overrides["canonical"] is None
        assert a.overrides["split_groups"] == []
        assert a.effective_action() == AliasAction.ACCEPT

    def test_explicit_action(self) -> None:
        a = AliasCorrection(
            cluster="c",
            members=["A", "B"],
            doubts=[_doubt()],
            overrides={"action": "veto"},
        )
        assert a.effective_action() == AliasAction.VETO

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AliasCorrection(
                cluster="c", members=["A", "B"], doubts=[_doubt()],
                overrides={"action": "frobnicate"},
            )
