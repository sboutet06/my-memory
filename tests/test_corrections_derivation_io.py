"""Derivation IO: YAML round-trip with inline hints + idempotent merge."""
from __future__ import annotations

from pathlib import Path

from corrections.derivation_io import (
    alias_path,
    entity_types_path,
    list_alias_corrections,
    list_entity_type_buckets,
    load_alias_correction,
    load_entity_type_bucket,
    make_slug,
    merge_alias_correction,
    merge_entity_type_bucket,
    save_alias_correction,
    save_entity_type_bucket,
)
from corrections.derivation_schemas import (
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


class TestSlug:
    def test_removes_accents_and_lowers(self) -> None:
        assert make_slug("Sébastien Boutet") == "sebastien_boutet"

    def test_collapses_whitespace_and_punctuation(self) -> None:
        assert make_slug("Plan — Prévention, des Risques!") == "plan_prevention_des_risques"

    def test_empty_fallback(self) -> None:
        assert make_slug("") == "unnamed"


class TestEntityTypeIO:
    def test_path_layout(self, tmp_path: Path) -> None:
        assert entity_types_path(tmp_path, "concept_fallback") == \
               tmp_path / "derivation" / "entity_types" / "concept_fallback.yaml"

    def test_roundtrip(self, tmp_path: Path) -> None:
        b = EntityTypeBucket(
            bucket="concept_fallback",
            entries=[
                EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                evidence_docs=["doc-1"]),
            ],
        )
        save_entity_type_bucket(tmp_path, b)
        loaded = load_entity_type_bucket(tmp_path, "concept_fallback")
        assert loaded is not None
        assert loaded.entries[0].name == "Gabriel"

    def test_yaml_has_hints(self, tmp_path: Path) -> None:
        b = EntityTypeBucket(bucket="b",
                             entries=[EntityTypeEntry(name="X", inferred_type="concept")])
        save_entity_type_bucket(tmp_path, b)
        raw = entity_types_path(tmp_path, "b").read_text()
        assert "pending | reviewed" in raw
        # entry-level hint listing allowed types
        assert "person" in raw and "organization" in raw and "location" in raw

    def test_merge_preserves_overrides(self) -> None:
        existing = EntityTypeBucket(
            bucket="b",
            status=CorrectionStatus.REVIEWED,
            entries=[
                EntityTypeEntry(name="Gabriel", inferred_type="concept",
                                override_type="person"),
                EntityTypeEntry(name="GhostOld", inferred_type="concept"),
            ],
        )
        fresh = [
            EntityTypeEntry(name="Gabriel", inferred_type="concept",
                            evidence_docs=["new-doc"]),
            EntityTypeEntry(name="Newbie", inferred_type="concept"),
        ]
        merged = merge_entity_type_bucket(existing, fresh, bucket="b")
        names = {e.name: e for e in merged.entries}
        # GhostOld dropped (no longer present); Gabriel keeps override but
        # refreshes evidence_docs; Newbie added with no override.
        assert set(names.keys()) == {"Gabriel", "Newbie"}
        assert names["Gabriel"].override_type == "person"
        assert names["Gabriel"].evidence_docs == ["new-doc"]
        assert names["Newbie"].override_type is None
        # Status preserved (user decision sticks).
        assert merged.status == CorrectionStatus.REVIEWED


class TestAliasIO:
    def test_path_layout(self, tmp_path: Path) -> None:
        assert alias_path(tmp_path, "sebastien_boutet") == \
               tmp_path / "derivation" / "aliases" / "sebastien_boutet.yaml"

    def test_roundtrip(self, tmp_path: Path) -> None:
        a = AliasCorrection(
            cluster="sebastien_boutet",
            members=["Sébastien Boutet", "SEBASTIEN BOUTET"],
            doubts=[_doubt()],
        )
        save_alias_correction(tmp_path, a)
        loaded = load_alias_correction(tmp_path, "sebastien_boutet")
        assert loaded is not None
        assert loaded.members[0] == "Sébastien Boutet"

    def test_yaml_has_hints(self, tmp_path: Path) -> None:
        a = AliasCorrection(cluster="c", members=["A", "B"], doubts=[_doubt()])
        save_alias_correction(tmp_path, a)
        raw = alias_path(tmp_path, "c").read_text()
        assert "pending | reviewed" in raw
        assert "accept" in raw and "merge" in raw and "veto" in raw and "split" in raw

    def test_merge_preserves_user_override(self) -> None:
        existing = AliasCorrection(
            cluster="c", members=["A", "B"], doubts=[_doubt()],
            overrides={"action": "veto"},
        )
        merged = merge_alias_correction(
            existing, AliasCorrection(
                cluster="c", members=["A", "B", "C"], doubts=[_doubt()],
            ),
        )
        assert merged.overrides["action"] == "veto"
        # Members refreshed (pipeline authoritative on cluster composition)
        assert merged.members == ["A", "B", "C"]


class TestListers:
    def test_list_empty(self, tmp_path: Path) -> None:
        assert list_entity_type_buckets(tmp_path) == []
        assert list_alias_corrections(tmp_path) == []

    def test_list_populated(self, tmp_path: Path) -> None:
        save_entity_type_bucket(tmp_path, EntityTypeBucket(bucket="a"))
        save_entity_type_bucket(tmp_path, EntityTypeBucket(bucket="b"))
        save_alias_correction(tmp_path, AliasCorrection(
            cluster="x", members=["A"], doubts=[_doubt()],
        ))
        assert [b.bucket for b in list_entity_type_buckets(tmp_path)] == ["a", "b"]
        assert [a.cluster for a in list_alias_corrections(tmp_path)] == ["x"]
