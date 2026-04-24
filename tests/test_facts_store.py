"""Tests for FactStore — JSONL-backed persistence layer.

Covers: empty-store initialization, append+reload, duplicate-ID
rejection, cross-instance persistence, query helpers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from facts.models import Claim, Conflict, Fact
from facts.store import DuplicateIDError, FactStore


@pytest.fixture
def store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "facts_store")


@pytest.fixture
def sample_fact() -> Fact:
    return Fact(
        subject_id="entity-1",
        predicate="address",
        canonical_value="10 Rue de la Paix, Paris",
        source_doc_id="doc-abc",
    )


@pytest.fixture
def sample_claim(sample_fact: Fact) -> Claim:
    return Claim(
        fact_id=sample_fact.id,
        source_doc_id="doc-abc",
        source_location="page:1",
        extractor="pack:bank_statement@1.0",
    )


class TestStoreInitialization:
    def test_creates_directory_if_absent(self, tmp_path: Path) -> None:
        store_path = tmp_path / "brand_new"
        assert not store_path.exists()
        FactStore(store_path)
        assert store_path.is_dir()

    def test_empty_store_zero_counts(self, store: FactStore) -> None:
        assert store.fact_count == 0
        assert store.claim_count == 0
        assert store.conflict_count == 0

    def test_empty_store_no_jsonl_files_required(self, tmp_path: Path) -> None:
        s = FactStore(tmp_path / "empty")
        assert s.fact_count == 0  # no files yet — no crash


class TestFactAppend:
    def test_append_increments_count(self, store: FactStore, sample_fact: Fact) -> None:
        store.append_fact(sample_fact)
        assert store.fact_count == 1

    def test_get_fact_after_append(self, store: FactStore, sample_fact: Fact) -> None:
        store.append_fact(sample_fact)
        retrieved = store.get_fact(sample_fact.id)
        assert retrieved is not None
        assert retrieved.id == sample_fact.id
        assert retrieved.predicate == sample_fact.predicate

    def test_get_nonexistent_fact_returns_none(self, store: FactStore) -> None:
        assert store.get_fact("no-such-id") is None

    def test_duplicate_fact_id_raises(self, store: FactStore, sample_fact: Fact) -> None:
        store.append_fact(sample_fact)
        with pytest.raises(DuplicateIDError):
            store.append_fact(sample_fact)

    def test_store_persists_across_instances(
        self, tmp_path: Path, sample_fact: Fact,
    ) -> None:
        store_path = tmp_path / "persist"
        s1 = FactStore(store_path)
        s1.append_fact(sample_fact)

        s2 = FactStore(store_path)
        assert s2.fact_count == 1
        assert s2.get_fact(sample_fact.id) is not None

    def test_reloaded_fact_has_correct_id(
        self, tmp_path: Path, sample_fact: Fact,
    ) -> None:
        store_path = tmp_path / "id_check"
        s1 = FactStore(store_path)
        s1.append_fact(sample_fact)
        s2 = FactStore(store_path)
        reloaded = s2.get_fact(sample_fact.id)
        assert reloaded is not None
        assert reloaded.id == sample_fact.id

    def test_facts_for_subject_returns_matching(self, store: FactStore) -> None:
        f1 = Fact(subject_id="e1", predicate="address", canonical_value="Paris", source_doc_id="d1")
        f2 = Fact(subject_id="e1", predicate="employer", canonical_value="Acme", source_doc_id="d1")
        f3 = Fact(subject_id="e2", predicate="address", canonical_value="Lyon", source_doc_id="d1")
        for f in (f1, f2, f3):
            store.append_fact(f)
        results = store.facts_for_subject("e1")
        assert len(results) == 2
        assert {f.predicate for f in results} == {"address", "employer"}

    def test_facts_for_subject_no_match_returns_empty(self, store: FactStore) -> None:
        assert store.facts_for_subject("unknown-entity") == []


class TestClaimAppend:
    def test_append_claim(
        self, store: FactStore, sample_fact: Fact, sample_claim: Claim,
    ) -> None:
        store.append_fact(sample_fact)
        store.append_claim(sample_claim)
        assert store.claim_count == 1

    def test_duplicate_claim_id_raises(
        self, store: FactStore, sample_fact: Fact, sample_claim: Claim,
    ) -> None:
        store.append_fact(sample_fact)
        store.append_claim(sample_claim)
        with pytest.raises(DuplicateIDError):
            store.append_claim(sample_claim)

    def test_claims_for_fact(
        self, store: FactStore, sample_fact: Fact, sample_claim: Claim,
    ) -> None:
        store.append_fact(sample_fact)
        store.append_claim(sample_claim)
        results = store.claims_for_fact(sample_fact.id)
        assert len(results) == 1
        assert results[0].id == sample_claim.id

    def test_claim_persists_across_instances(
        self, tmp_path: Path, sample_fact: Fact, sample_claim: Claim,
    ) -> None:
        store_path = tmp_path / "claim_persist"
        s1 = FactStore(store_path)
        s1.append_fact(sample_fact)
        s1.append_claim(sample_claim)
        s2 = FactStore(store_path)
        assert s2.claim_count == 1


class TestConflictAppend:
    def test_append_conflict(self, store: FactStore) -> None:
        c = Conflict(subject_id="e", predicate="address", competing_fact_ids=["f1", "f2"])
        store.append_conflict(c)
        assert store.conflict_count == 1

    def test_duplicate_conflict_raises(self, store: FactStore) -> None:
        c = Conflict(subject_id="e", predicate="address")
        store.append_conflict(c)
        with pytest.raises(DuplicateIDError):
            store.append_conflict(c)

    def test_get_conflict_returns_correct(self, store: FactStore) -> None:
        c = Conflict(subject_id="e", predicate="birthdate")
        store.append_conflict(c)
        retrieved = store.get_conflict(c.id)
        assert retrieved is not None
        assert retrieved.status == "open"

    def test_get_nonexistent_conflict_returns_none(self, store: FactStore) -> None:
        assert store.get_conflict("no-such") is None

    def test_open_conflicts_returns_only_open(self, store: FactStore) -> None:
        c1 = Conflict(subject_id="e1", predicate="address", status="open")
        c2 = Conflict(subject_id="e2", predicate="birthdate", status="resolved_manually")
        store.append_conflict(c1)
        store.append_conflict(c2)
        open_list = store.open_conflicts()
        assert len(open_list) == 1
        assert open_list[0].id == c1.id
