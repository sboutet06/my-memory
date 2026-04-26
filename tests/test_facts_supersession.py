"""Tests for facts.supersession — Phase 8.4 supersession engine.

For time_varying predicates: a Fact with later valid_from closes the
earlier one (sets its valid_to = later.valid_from - 1 day). Earlier
fact is NOT deleted — history is preserved.

For time_invariant or allow_multi predicates: no supersession (the
conflict detector handles invariant divergence; allow_multi means
coexistence is intentional).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from facts.models import Fact, Predicate
from facts.predicates import PredicateRegistry
from facts.store import FactStore


def _make_fact(
    subject_id: str,
    predicate: str,
    value: str,
    source_doc_id: str,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> Fact:
    return Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=value,
        value=value,
        source_doc_id=source_doc_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )


@pytest.fixture
def tmp_store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "facts")


@pytest.fixture
def registry() -> PredicateRegistry:
    r = PredicateRegistry()
    r.register(Predicate(name="address", time_varying=True, allow_multi=False))
    r.register(Predicate(name="employer", time_varying=True, allow_multi=False))
    r.register(Predicate(name="birthdate", time_varying=False, allow_multi=False))
    r.register(Predicate(name="transaction", time_varying=False, allow_multi=True))
    return r


class TestRunSupersession:
    def test_import(self) -> None:
        from facts.supersession import run_supersession  # noqa: F401

    def test_no_facts_returns_zero(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        assert run_supersession(tmp_store, registry) == 0

    def test_single_fact_no_change(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        f = _make_fact("p1", "address", "10 rue A", "doc-1", valid_from=date(2010, 1, 1))
        tmp_store.append_fact(f)
        run_supersession(tmp_store, registry)
        assert tmp_store.get_fact(f.id).valid_to is None

    def test_two_addresses_older_gets_valid_to_closed(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        older = _make_fact("p1", "address", "10 rue A", "doc-1", valid_from=date(2010, 1, 1))
        newer = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        tmp_store.append_fact(older)
        tmp_store.append_fact(newer)

        updated = run_supersession(tmp_store, registry)
        assert updated >= 1
        # Older fact's valid_to set to newer.valid_from - 1 day = 2015-05-31
        assert tmp_store.get_fact(older.id).valid_to == date(2015, 5, 31)
        # Newer fact still open-ended
        assert tmp_store.get_fact(newer.id).valid_to is None

    def test_three_step_chain_closed_pairwise(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "address", "10 rue A", "doc-1", valid_from=date(2010, 1, 1))
        f2 = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        f3 = _make_fact("p1", "address", "30 rue C", "doc-3", valid_from=date(2020, 9, 1))
        for f in [f1, f2, f3]:
            tmp_store.append_fact(f)

        run_supersession(tmp_store, registry)
        assert tmp_store.get_fact(f1.id).valid_to == date(2015, 5, 31)
        assert tmp_store.get_fact(f2.id).valid_to == date(2020, 8, 31)
        assert tmp_store.get_fact(f3.id).valid_to is None

    def test_invariant_predicate_skipped(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        """Time-invariant predicates (birthdate) don't supersede — those are conflicts."""
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "birthdate", "1985-01-01", "doc-1",
                        valid_from=date(1985, 1, 1))
        f2 = _make_fact("p1", "birthdate", "1986-02-02", "doc-2",
                        valid_from=date(1986, 2, 2))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        run_supersession(tmp_store, registry)
        # Neither should get valid_to set — birthdate is invariant.
        assert tmp_store.get_fact(f1.id).valid_to is None
        assert tmp_store.get_fact(f2.id).valid_to is None

    def test_allow_multi_predicate_skipped(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        """Transactions coexist — supersession is meaningless."""
        from facts.supersession import run_supersession

        f1 = _make_fact("acc", "transaction", "tx 100EUR 2024-01-01", "doc-1",
                        valid_from=date(2024, 1, 1))
        f2 = _make_fact("acc", "transaction", "tx 200EUR 2024-02-01", "doc-1",
                        valid_from=date(2024, 2, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        run_supersession(tmp_store, registry)
        assert tmp_store.get_fact(f1.id).valid_to is None
        assert tmp_store.get_fact(f2.id).valid_to is None

    def test_facts_without_valid_from_skipped(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        """Can't reason about supersession without valid_from."""
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "address", "10 rue A", "doc-1")  # valid_from=None
        f2 = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        run_supersession(tmp_store, registry)
        assert tmp_store.get_fact(f1.id).valid_to is None  # untouched
        assert tmp_store.get_fact(f2.id).valid_to is None  # nothing later

    def test_idempotent_second_run_no_changes(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "address", "10 rue A", "doc-1", valid_from=date(2010, 1, 1))
        f2 = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        first = run_supersession(tmp_store, registry)
        second = run_supersession(tmp_store, registry)
        # First run sets valid_to on older; second run finds nothing to update.
        assert second == 0
        assert tmp_store.get_fact(f1.id).valid_to == date(2015, 5, 31)

    def test_preexisting_valid_to_not_overwritten(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        """Manual valid_to (e.g., from corrections) wins."""
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "address", "10 rue A", "doc-1",
                        valid_from=date(2010, 1, 1), valid_to=date(2014, 12, 31))
        f2 = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        run_supersession(tmp_store, registry)
        # Existing valid_to preserved.
        assert tmp_store.get_fact(f1.id).valid_to == date(2014, 12, 31)

    def test_different_subjects_independent(
        self, tmp_store: FactStore, registry: PredicateRegistry,
    ) -> None:
        from facts.supersession import run_supersession

        # Person 1: two addresses
        a1 = _make_fact("p1", "address", "10A", "d1", valid_from=date(2010, 1, 1))
        a2 = _make_fact("p1", "address", "10B", "d2", valid_from=date(2015, 1, 1))
        # Person 2: single address
        b1 = _make_fact("p2", "address", "20A", "d3", valid_from=date(2012, 1, 1))
        for f in [a1, a2, b1]:
            tmp_store.append_fact(f)

        run_supersession(tmp_store, registry)
        assert tmp_store.get_fact(a1.id).valid_to == date(2014, 12, 31)
        assert tmp_store.get_fact(a2.id).valid_to is None
        assert tmp_store.get_fact(b1.id).valid_to is None

    def test_persisted_to_disk(
        self, tmp_store: FactStore, registry: PredicateRegistry, tmp_path: Path,
    ) -> None:
        """Reload from disk should show the supersession results."""
        from facts.supersession import run_supersession

        f1 = _make_fact("p1", "address", "10 rue A", "doc-1", valid_from=date(2010, 1, 1))
        f2 = _make_fact("p1", "address", "20 rue B", "doc-2", valid_from=date(2015, 6, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)
        run_supersession(tmp_store, registry)

        # Reload
        reloaded = FactStore(tmp_path / "facts")
        assert reloaded.get_fact(f1.id).valid_to == date(2015, 5, 31)


class TestFactStoreReplaceFacts:
    """The supersession engine needs replace_facts() — append-only doesn't suffice."""

    def test_replace_facts_overwrites_all(self, tmp_store: FactStore) -> None:
        f1 = _make_fact("p1", "address", "A", "d1", valid_from=date(2010, 1, 1))
        f2 = _make_fact("p1", "address", "B", "d2", valid_from=date(2015, 1, 1))
        tmp_store.append_fact(f1)
        tmp_store.append_fact(f2)

        f1_updated = _make_fact("p1", "address", "A", "d1",
                                valid_from=date(2010, 1, 1),
                                valid_to=date(2014, 12, 31))
        # Same ID as f1 (id is content-addressable on subj/pred/value/doc)
        assert f1_updated.id == f1.id

        tmp_store.replace_facts([f1_updated, f2])
        assert tmp_store.get_fact(f1.id).valid_to == date(2014, 12, 31)
        assert tmp_store.get_fact(f2.id).valid_to is None
        assert tmp_store.fact_count == 2

    def test_replace_facts_persisted(
        self, tmp_store: FactStore, tmp_path: Path,
    ) -> None:
        f = _make_fact("p1", "address", "A", "d1", valid_from=date(2010, 1, 1))
        tmp_store.append_fact(f)
        f_updated = _make_fact("p1", "address", "A", "d1",
                               valid_from=date(2010, 1, 1),
                               valid_to=date(2020, 12, 31))
        tmp_store.replace_facts([f_updated])

        reloaded = FactStore(tmp_path / "facts")
        assert reloaded.get_fact(f.id).valid_to == date(2020, 12, 31)
