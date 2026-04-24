"""Tests for facts.detector — conflict detection.

TDD: these fail until facts/detector.py is implemented.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from facts.models import Claim, Conflict, Fact, Predicate
from facts.predicates import PredicateRegistry
from facts.store import FactStore


def _make_fact(subject_id: str, predicate: str, value: str, source_doc_id: str) -> Fact:
    return Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=value,
        value=value,
        source_doc_id=source_doc_id,
    )


@pytest.fixture
def tmp_store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path)


@pytest.fixture
def registry() -> PredicateRegistry:
    r = PredicateRegistry()
    r.register(Predicate(name="address", time_varying=True, allow_multi=False))
    r.register(Predicate(name="birthdate", time_varying=False, allow_multi=False))
    r.register(Predicate(name="transaction", allow_multi=True))
    return r


class TestDetectConflictForFact:
    def test_import(self) -> None:
        from facts.detector import detect_conflict_for_fact  # noqa: F401

    def test_single_fact_no_conflict(self, tmp_store: FactStore, registry: PredicateRegistry) -> None:
        from facts.detector import detect_conflict_for_fact

        f = _make_fact("e1", "address", "10 rue A", "doc-1")
        tmp_store.append_fact(f)
        conflict = detect_conflict_for_fact(tmp_store, f, registry)
        assert conflict is None

    def test_two_facts_same_value_different_doc_no_conflict(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_conflict_for_fact

        f1 = _make_fact("e1", "address", "10 rue A", "doc-1")
        f2 = _make_fact("e1", "address", "10 rue A", "doc-2")
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        conflict = detect_conflict_for_fact(tmp_store, f2, registry)
        assert conflict is None

    def test_two_facts_different_value_emits_conflict(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_conflict_for_fact

        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        conflict = detect_conflict_for_fact(tmp_store, f2, registry)
        assert conflict is not None
        assert conflict.subject_id == "e1"
        assert conflict.predicate == "birthdate"
        assert set(conflict.competing_fact_ids) == {f1.id, f2.id}
        assert conflict.status == "open"

    def test_allow_multi_no_conflict(self, tmp_store: FactStore, registry: PredicateRegistry) -> None:
        from facts.detector import detect_conflict_for_fact

        f1 = _make_fact("account-1", "transaction", "€100 2024-01-01", "doc-1")
        f2 = _make_fact("account-1", "transaction", "€200 2024-01-02", "doc-2")
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        conflict = detect_conflict_for_fact(tmp_store, f2, registry)
        assert conflict is None

    def test_unknown_predicate_defaults_to_conflict(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_conflict_for_fact

        f1 = _make_fact("e1", "mystery_field", "val-A", "doc-1")
        f2 = _make_fact("e1", "mystery_field", "val-B", "doc-2")
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        conflict = detect_conflict_for_fact(tmp_store, f2, registry)
        assert conflict is not None

    def test_conflict_written_to_store(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_conflict_for_fact

        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        conflict = detect_conflict_for_fact(tmp_store, f2, registry)
        assert conflict is not None
        stored = tmp_store.get_conflict(conflict.id)
        assert stored is not None
        assert stored.status == "open"


class TestDetectAllConflicts:
    def test_import(self) -> None:
        from facts.detector import detect_all_conflicts  # noqa: F401

    def test_empty_store_no_conflicts(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        conflicts = detect_all_conflicts(tmp_store, registry)
        assert conflicts == []

    def test_finds_one_conflict(self, tmp_store: FactStore, registry: PredicateRegistry) -> None:
        from facts.detector import detect_all_conflicts

        tmp_store.append_fact(_make_fact("e1", "birthdate", "1985-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1986-02-02", "doc-2"))
        conflicts = detect_all_conflicts(tmp_store, registry)
        assert len(conflicts) == 1
        assert conflicts[0].predicate == "birthdate"

    def test_finds_multiple_conflicts(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        # birthdate conflict
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1985-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1986-02-02", "doc-2"))
        # address conflict
        tmp_store.append_fact(_make_fact("e1", "address", "10 rue A", "doc-3"))
        tmp_store.append_fact(_make_fact("e1", "address", "20 ave B", "doc-4"))
        conflicts = detect_all_conflicts(tmp_store, registry)
        assert len(conflicts) == 2

    def test_allow_multi_not_reported(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        tmp_store.append_fact(_make_fact("acc-1", "transaction", "€100 2024-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("acc-1", "transaction", "€200 2024-01-02", "doc-2"))
        conflicts = detect_all_conflicts(tmp_store, registry)
        assert conflicts == []

    def test_idempotent_second_run_no_duplicates(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        tmp_store.append_fact(_make_fact("e1", "birthdate", "1985-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1986-02-02", "doc-2"))
        detect_all_conflicts(tmp_store, registry)
        detect_all_conflicts(tmp_store, registry)
        assert tmp_store.conflict_count == 1

    def test_replaces_stale_conflict_when_fact_added(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        tmp_store.append_fact(_make_fact("e1", "birthdate", "1985-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1986-02-02", "doc-2"))
        detect_all_conflicts(tmp_store, registry)
        # add a third conflicting fact
        f3 = _make_fact("e1", "birthdate", "1987-03-03", "doc-3")
        tmp_store.append_fact(f3)
        conflicts = detect_all_conflicts(tmp_store, registry)
        assert len(conflicts) == 1
        assert f3.id in conflicts[0].competing_fact_ids

    def test_conflicts_persisted_to_store(
        self, tmp_store: FactStore, registry: PredicateRegistry
    ) -> None:
        from facts.detector import detect_all_conflicts

        tmp_store.append_fact(_make_fact("e1", "birthdate", "1985-01-01", "doc-1"))
        tmp_store.append_fact(_make_fact("e1", "birthdate", "1986-02-02", "doc-2"))
        detect_all_conflicts(tmp_store, registry)
        assert tmp_store.conflict_count == 1


class TestFactsForSubjectPredicate:
    """FactStore helper used by the detector."""

    def test_facts_for_subject_predicate(self, tmp_store: FactStore) -> None:
        f1 = _make_fact("e1", "address", "10 rue A", "doc-1")
        f2 = _make_fact("e1", "address", "20 ave B", "doc-2")
        f3 = _make_fact("e1", "birthdate", "1985-01-01", "doc-3")
        f4 = _make_fact("e2", "address", "30 blvd C", "doc-4")
        for f in [f1, f2, f3, f4]:
            tmp_store.append_fact(f)

        result = tmp_store.facts_for_subject_predicate("e1", "address")
        assert len(result) == 2
        assert {f.id for f in result} == {f1.id, f2.id}

    def test_facts_for_subject_predicate_empty(self, tmp_store: FactStore) -> None:
        assert tmp_store.facts_for_subject_predicate("nonexistent", "address") == []
