"""Tests for Fact/Claim/Conflict/Predicate Pydantic schemas.

Covers: ID stability under field reordering, validation, round-trip
serialization, invalid-payload rejection.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from facts.models import Claim, Conflict, Fact, Predicate, _sha256


class TestSha256Helper:
    def test_deterministic(self) -> None:
        assert _sha256("a", "b", "c") == _sha256("a", "b", "c")

    def test_part_order_matters(self) -> None:
        assert _sha256("a", "b") != _sha256("b", "a")

    def test_empty_parts_deterministic(self) -> None:
        assert _sha256("", "", "") == _sha256("", "", "")


class TestFactId:
    def _make(self, **overrides) -> Fact:
        defaults = dict(
            subject_id="entity-1",
            predicate="address",
            canonical_value="10 Rue de la Paix, Paris",
            value="10 Rue de la Paix, Paris",
            source_doc_id="doc-abc123",
        )
        defaults.update(overrides)
        return Fact(**defaults)

    def test_id_is_sha256_of_key_fields(self) -> None:
        f = self._make()
        expected = _sha256("entity-1", "address", "10 Rue de la Paix, Paris", "doc-abc123")
        assert f.id == expected

    def test_id_stable_when_non_key_fields_differ(self) -> None:
        f1 = self._make(confidence=0.8)
        f2 = self._make(confidence=1.0)
        assert f1.id == f2.id

    def test_id_stable_when_valid_from_differs(self) -> None:
        f1 = self._make(valid_from=date(2020, 1, 1))
        f2 = self._make(valid_from=date(2023, 6, 1))
        assert f1.id == f2.id

    def test_id_changes_with_different_source_doc(self) -> None:
        f1 = self._make(source_doc_id="doc-aaa")
        f2 = self._make(source_doc_id="doc-bbb")
        assert f1.id != f2.id

    def test_id_changes_with_different_predicate(self) -> None:
        f1 = self._make(predicate="address")
        f2 = self._make(predicate="employer")
        assert f1.id != f2.id

    def test_id_changes_with_different_canonical_value(self) -> None:
        f1 = self._make(canonical_value="Paris")
        f2 = self._make(canonical_value="Lyon")
        assert f1.id != f2.id

    def test_id_changes_with_different_subject(self) -> None:
        f1 = self._make(subject_id="entity-1")
        f2 = self._make(subject_id="entity-2")
        assert f1.id != f2.id


class TestFactValidation:
    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(Exception):
            Fact(
                subject_id="e", predicate="p", canonical_value="v",
                source_doc_id="d", confidence=1.5,
            )

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(Exception):
            Fact(
                subject_id="e", predicate="p", canonical_value="v",
                source_doc_id="d", confidence=-0.1,
            )

    def test_confidence_boundary_values_accepted(self) -> None:
        Fact(subject_id="e", predicate="p", canonical_value="v", source_doc_id="d", confidence=0.0)
        Fact(subject_id="e", predicate="p", canonical_value="v", source_doc_id="d", confidence=1.0)

    def test_missing_subject_id_rejected(self) -> None:
        with pytest.raises(Exception):
            Fact(predicate="p", canonical_value="v", source_doc_id="d")  # type: ignore[call-arg]

    def test_round_trip_json(self) -> None:
        f = Fact(
            subject_id="entity-1",
            predicate="address",
            canonical_value="Paris",
            value={"street": "Rue de Rivoli", "city": "Paris"},
            source_doc_id="doc-xyz",
            valid_from=date(2020, 1, 1),
            confidence=0.95,
        )
        restored = Fact.model_validate_json(f.model_dump_json())
        assert restored.id == f.id
        assert restored.subject_id == f.subject_id
        assert restored.predicate == f.predicate
        assert restored.canonical_value == f.canonical_value
        assert restored.confidence == f.confidence

    def test_id_included_in_json_output(self) -> None:
        f = Fact(subject_id="e", predicate="p", canonical_value="v", source_doc_id="d")
        data = json.loads(f.model_dump_json())
        assert "id" in data
        assert data["id"] == f.id

    def test_id_recomputed_on_deserialize_matches_stored(self) -> None:
        f = Fact(subject_id="e", predicate="p", canonical_value="v", source_doc_id="d")
        raw = json.loads(f.model_dump_json())
        assert raw["id"] == f.id
        restored = Fact.model_validate(raw)
        assert restored.id == f.id


class TestClaimId:
    def _make(self, **overrides) -> Claim:
        defaults = dict(
            fact_id="fact-abc",
            source_doc_id="doc-123",
            source_location="page:2,row:5",
            extractor="pack:bank_statement@1.0",
        )
        defaults.update(overrides)
        return Claim(**defaults)

    def test_id_is_sha256_of_key_fields(self) -> None:
        c = self._make()
        expected = _sha256("fact-abc", "doc-123", "page:2,row:5", "pack:bank_statement@1.0")
        assert c.id == expected

    def test_id_stable_when_confidence_differs(self) -> None:
        c1 = self._make(confidence=0.8)
        c2 = self._make(confidence=1.0)
        assert c1.id == c2.id

    def test_id_changes_with_different_extractor(self) -> None:
        c1 = self._make(extractor="pack:bank_statement@1.0")
        c2 = self._make(extractor="pack:bank_statement@2.0")
        assert c1.id != c2.id

    def test_id_changes_with_different_source_location(self) -> None:
        c1 = self._make(source_location="page:1")
        c2 = self._make(source_location="page:2")
        assert c1.id != c2.id

    def test_round_trip_json(self) -> None:
        c = self._make()
        restored = Claim.model_validate_json(c.model_dump_json())
        assert restored.id == c.id
        assert restored.fact_id == c.fact_id

    def test_missing_fact_id_rejected(self) -> None:
        with pytest.raises(Exception):
            Claim(source_doc_id="d", source_location="", extractor="e")  # type: ignore[call-arg]


class TestConflict:
    def test_status_defaults_to_open(self) -> None:
        c = Conflict(subject_id="e", predicate="address")
        assert c.status == "open"

    def test_id_based_on_subject_and_predicate(self) -> None:
        c = Conflict(subject_id="e", predicate="address")
        assert c.id == _sha256("e", "address")

    def test_id_stable_when_competing_facts_differ(self) -> None:
        c1 = Conflict(subject_id="e", predicate="p", competing_fact_ids=["f1"])
        c2 = Conflict(subject_id="e", predicate="p", competing_fact_ids=["f1", "f2"])
        assert c1.id == c2.id

    def test_round_trip_json(self) -> None:
        c = Conflict(
            subject_id="e",
            predicate="address",
            competing_fact_ids=["f1", "f2"],
        )
        restored = Conflict.model_validate_json(c.model_dump_json())
        assert restored.id == c.id
        assert restored.competing_fact_ids == ["f1", "f2"]

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(Exception):
            Conflict(subject_id="e", predicate="p", status="unknown_status")  # type: ignore[call-arg]


class TestPredicate:
    def test_defaults(self) -> None:
        p = Predicate(name="address")
        assert p.time_varying is False
        assert p.allow_multi is False
        assert p.description == ""

    def test_name_required(self) -> None:
        with pytest.raises(Exception):
            Predicate()  # type: ignore[call-arg]

    def test_time_varying_set(self) -> None:
        p = Predicate(name="address", time_varying=True)
        assert p.time_varying is True

    def test_allow_multi_set(self) -> None:
        p = Predicate(name="tags", allow_multi=True)
        assert p.allow_multi is True
