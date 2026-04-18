"""Derivation overlay: apply type + alias overrides at read time."""
from __future__ import annotations

from corrections.derivation_overlay import (
    AliasDecision,
    apply_entity_type_overrides,
    collect_alias_decisions,
    collect_entity_type_overrides,
)
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


def _doubt():
    return Doubt(
        field="merge_decision", inferred_value="merge",
        confidence=Confidence.MEDIUM, rationale="r",
        suggested_action=SuggestedAction.CONFIRM,
    )


class TestEntityTypeOverrides:
    def test_collect_from_single_bucket(self) -> None:
        b = EntityTypeBucket(
            bucket="concept_fallback",
            entries=[
                EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                override_type="person"),
                EntityTypeEntry(name="NoOverride", inferred_type="concept"),
            ],
        )
        assert collect_entity_type_overrides([b]) == {"Gabriel": "person"}

    def test_later_bucket_wins_on_conflict(self) -> None:
        b1 = EntityTypeBucket(
            bucket="a",
            entries=[EntityTypeEntry(name="X", inferred_type="concept",
                                     override_type="person")],
        )
        b2 = EntityTypeBucket(
            bucket="b",
            entries=[EntityTypeEntry(name="X", inferred_type="concept",
                                     override_type="location")],
        )
        assert collect_entity_type_overrides([b1, b2]) == {"X": "location"}

    def test_apply_overrides_to_graph(self) -> None:
        graph = {
            "Gabriel": {"entity_type": "concept"},
            "Alice": {"entity_type": "person"},
        }
        out = apply_entity_type_overrides(graph, {"Gabriel": "person"})
        assert out["Gabriel"]["entity_type"] == "person"
        assert out["Alice"]["entity_type"] == "person"
        # Input not mutated (returns a copy).
        assert graph["Gabriel"]["entity_type"] == "concept"


class TestAliasDecisions:
    def test_collect_accept_by_default(self) -> None:
        a = AliasCorrection(
            cluster="c", members=["A", "B"], doubts=[_doubt()],
        )
        decisions = collect_alias_decisions([a])
        assert decisions[0].action == AliasAction.ACCEPT

    def test_merge_with_canonical(self) -> None:
        a = AliasCorrection(
            cluster="c", members=["A", "B", "C"], doubts=[_doubt()],
            overrides={"action": "merge", "canonical": "A"},
        )
        d = collect_alias_decisions([a])[0]
        assert d.action == AliasAction.MERGE
        assert d.canonical == "A"
        assert d.members == ["A", "B", "C"]

    def test_split_preserves_groups(self) -> None:
        a = AliasCorrection(
            cluster="c", members=["A", "B", "C", "D"], doubts=[_doubt()],
            overrides={"action": "split", "split_groups": [["A", "B"], ["C", "D"]]},
        )
        d = collect_alias_decisions([a])[0]
        assert d.action == AliasAction.SPLIT
        assert d.split_groups == [["A", "B"], ["C", "D"]]

    def test_skips_pending_without_override(self) -> None:
        # A pending correction with no override → reported as ACCEPT.
        a = AliasCorrection(
            cluster="c", members=["A", "B"], doubts=[_doubt()],
        )
        assert a.status == CorrectionStatus.PENDING
        d = collect_alias_decisions([a])[0]
        assert d.action == AliasAction.ACCEPT
