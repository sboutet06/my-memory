"""Derivation-layer doubts emitter — pure function tests."""
from __future__ import annotations

from corrections.derivation_emitter import (
    emit_alias_corrections,
    emit_entity_type_buckets,
)
from corrections.derivation_schemas import CorrectionStatus


def _node(entity_type="concept", original_entity_type=None,
          document_ids=None):
    out = {"entity_type": entity_type}
    if original_entity_type:
        out["original_entity_type"] = original_entity_type
    if document_ids is not None:
        out["document_ids"] = document_ids
    return out


class TestEntityTypeEmitter:
    def test_all_allowed_no_doubts(self) -> None:
        graph = {
            "Alice": _node("person"),
            "ACME": _node("organization"),
        }
        buckets = emit_entity_type_buckets(graph, fallback="concept")
        assert buckets == []

    def test_document_ids_from_sep_joined_string(self) -> None:
        """LightRAG stores document_ids as a <SEP>-joined string on load."""
        graph = {
            "Gabriel": _node("concept", document_ids="doc-1<SEP>doc-2"),
        }
        buckets = emit_entity_type_buckets(graph)
        entry = buckets[0].entries[0]
        assert entry.evidence_docs == ["doc-1", "doc-2"]

    def test_concept_fallback_bucket(self) -> None:
        graph = {
            "Gabriel": _node("concept", document_ids=["doc-1"]),
            "Xylophone": _node("concept"),
            "Alice": _node("person"),
        }
        buckets = emit_entity_type_buckets(graph, fallback="concept")
        assert len(buckets) == 1
        b = buckets[0]
        assert b.bucket == "concept_fallback"
        names = {e.name for e in b.entries}
        assert names == {"Gabriel", "Xylophone"}
        g = next(e for e in b.entries if e.name == "Gabriel")
        assert g.inferred_type == "concept"
        assert g.evidence_docs == ["doc-1"]

    def test_remapped_singletons_bucket(self) -> None:
        graph = {
            "Chandelier": _node("concept", original_entity_type="lighting"),
            "Trail": _node("concept", original_entity_type="route"),
            "Gabriel": _node("concept"),  # plain fallback, no singleton
        }
        buckets = emit_entity_type_buckets(graph, fallback="concept")
        bucket_names = {b.bucket for b in buckets}
        assert bucket_names == {"concept_fallback", "remapped_singletons"}

        singletons = next(b for b in buckets if b.bucket == "remapped_singletons")
        names = {e.name for e in singletons.entries}
        assert names == {"Chandelier", "Trail"}

        fallback = next(b for b in buckets if b.bucket == "concept_fallback")
        fb_names = {e.name for e in fallback.entries}
        assert "Gabriel" in fb_names
        # Singletons ALSO appear in concept_fallback (they did get remapped
        # to concept) — keeping them in both buckets lets the user decide
        # via either view.
        assert "Chandelier" in fb_names


class TestAliasEmitter:
    def test_no_ambiguous(self) -> None:
        assert emit_alias_corrections(ambiguous_groups=[]) == []

    def test_one_group(self) -> None:
        corrections = emit_alias_corrections(ambiguous_groups=[
            ["Plan Prévention Miniers", "Plan Prévention Technologiques", "Plan Prévention"],
        ])
        assert len(corrections) == 1
        c = corrections[0]
        assert c.status == CorrectionStatus.PENDING
        assert c.cluster.startswith("plan_prevention")
        assert set(c.members) == {
            "Plan Prévention Miniers", "Plan Prévention Technologiques", "Plan Prévention",
        }
        assert len(c.doubts) == 1
        assert c.doubts[0].field == "merge_decision"

    def test_distinct_slugs_for_distinct_groups(self) -> None:
        corrections = emit_alias_corrections(ambiguous_groups=[
            ["Alice Martin", "Alice Martine"],
            ["Les Adrets", "Les Adrets-de-l'Estérel"],
        ])
        slugs = [c.cluster for c in corrections]
        assert len(set(slugs)) == 2
